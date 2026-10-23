"""Đọc demo bundle đã export; chỉ phục vụ file nằm trong allow-list và đúng checksum.

Trạng thái xuất bản (đang công khai hay đã bỏ) nằm ở catalog trong DB (`samples/catalog.py`), không ở file đánh dấu.
"""

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from src.services.orchestration.artifacts import sha256_file
from src.services.orchestration.samples.models import DemoFile, DemoManifest, DemoSource

if TYPE_CHECKING:
    from src.services.orchestration.samples.catalog import DemoCatalog

logger = logging.getLogger(__name__)


class DemoUnavailableError(LookupError):
    """Deployment chưa có demo bundle (hoặc bundle hỏng); UI ẩn kịch bản demo."""


class DemoBundle:
    """Bundle read-only tại `<root>/manifest.json` + `<root>/files/<name>`."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def manifest(self) -> DemoManifest:
        """Đọc và validate manifest; thiếu/hỏng → DemoUnavailableError."""
        path = self.root / "manifest.json"
        if not path.is_file():
            raise DemoUnavailableError("Chưa có demo bundle trên deployment này")
        try:
            return DemoManifest.model_validate_json(path.read_bytes())
        except ValueError as error:
            raise DemoUnavailableError("Demo bundle manifest không hợp lệ") from error

    def file(self, name: str) -> tuple[DemoFile, Path]:
        """Resolve file theo tên trong allow-list, kiểm size + checksum trước khi trả."""
        entry = next((item for item in self.manifest().files() if item.name == name), None)
        if entry is None:
            raise DemoUnavailableError("File không thuộc demo bundle")
        path = (self.root / "files" / entry.name).resolve()
        if not path.is_relative_to(self.root / "files") or not path.is_file():
            raise DemoUnavailableError("File demo bị thiếu")
        if path.stat().st_size != entry.size_bytes or sha256_file(path) != entry.checksum:
            raise DemoUnavailableError("File demo sai checksum; export lại bundle")
        return entry, path


class SampleSummary(BaseModel):
    """Thẻ video mẫu ở bước tải video: đủ để hiển thị, không lộ đường dẫn máy chủ."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    title: str
    description: str
    origin: str
    source: DemoSource
    cover: str | None
    video: DemoFile | None
    frame_count: int | None
    total_seconds: float | None
    has_processing: bool
    machine: dict[str, str]


_SAMPLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class DemoLibrary:
    """Thư viện video mẫu đã xử lý sẵn.

    `root` có `manifest.json` → một mẫu (tương thích bundle đơn cũ, id = `demo_id`);
    ngược lại mỗi thư mục con có `manifest.json` là một mẫu, id = tên thư mục.

    Có `catalog` thì chỉ mẫu ở trạng thái `published` trong catalog mới được liệt kê (bundle đơn cũ: trừ khi catalog
    ghi đã bỏ). Không có catalog (script, test đọc thẳng thư mục) thì liệt kê theo đĩa.
    """

    def __init__(self, root: Path, catalog: "DemoCatalog | None" = None) -> None:
        self.root = root.expanduser().resolve()
        self.catalog = catalog

    def bundles(self) -> dict[str, DemoBundle]:
        """Các bundle theo id; thư mục tên không an toàn bị bỏ qua."""
        if (self.root / "manifest.json").is_file():
            single = DemoBundle(self.root)
            try:
                demo_id = single.manifest().demo_id
            except DemoUnavailableError:
                return {}
            if self.catalog is not None:
                record = self.catalog.get(demo_id)
                if record is not None and record.state != "published":
                    return {}
            return {demo_id: single}
        if not self.root.is_dir():
            return {}
        published = self.catalog.published_ids() if self.catalog is not None else None
        return {
            child.name: DemoBundle(child)
            for child in sorted(self.root.iterdir())
            if child.is_dir()
            and _SAMPLE_ID.fullmatch(child.name)
            and (child / "manifest.json").is_file()
            and (published is None or child.name in published)
        }

    def bundle(self, sample_id: str) -> DemoBundle:
        """Bundle theo id; không có → DemoUnavailableError."""
        found = self.bundles().get(sample_id)
        if found is None:
            raise DemoUnavailableError("Không có video mẫu này")
        return found

    def unpublish(self, sample_id: str) -> None:
        """Gỡ mẫu khỏi thư viện công khai (đổi trạng thái trong catalog); giữ mọi file trên đĩa và trong kho."""
        bundle = self.bundle(sample_id)
        if not bundle.root.is_relative_to(self.root):
            raise DemoUnavailableError("Mẫu không thuộc thư viện demo")
        bundle.manifest()
        if self.catalog is None:
            raise DemoUnavailableError("Thư viện demo chưa gắn catalog")
        if self.catalog.get(sample_id) is None:
            # Bundle đơn cũ hoặc thư mục chép tay chưa nhập: ghi dòng catalog từ đĩa để trạng thái bỏ được lưu lại.
            from src.services.orchestration.samples.catalog import record_from_disk

            self.catalog.save(record_from_disk(bundle.root, sample_id, state="unpublished", actor=None))
            return
        self.catalog.set_state(sample_id, "unpublished")

    def summaries(self) -> list[SampleSummary]:
        """Thẻ của mọi mẫu hợp lệ; bundle hỏng bị bỏ qua (có log) thay vì làm hỏng cả danh sách."""
        items: list[SampleSummary] = []
        for sample_id, bundle in self.bundles().items():
            try:
                manifest = bundle.manifest()
            except DemoUnavailableError:
                logger.warning("Bỏ qua demo bundle hỏng: %s", sample_id)
                continue
            recorded = [stage for stage in manifest.stages if stage.state == "succeeded"]
            known = [stage.duration_seconds for stage in recorded if stage.duration_seconds is not None]
            # Chỉ báo tổng khi mọi stage có thời lượng đo được; thiếu một stage → không đoán.
            total = sum(known) if recorded and len(known) == len(recorded) else None
            cover = manifest.frames[len(manifest.frames) // 2].name if manifest.frames else None
            items.append(
                SampleSummary(
                    sample_id=sample_id,
                    title=manifest.title,
                    description=manifest.description,
                    origin=manifest.origin,
                    source=manifest.source,
                    cover=cover,
                    video=manifest.video,
                    frame_count=manifest.frame_count,
                    total_seconds=total,
                    has_processing=manifest.processing is not None,
                    machine=manifest.machine,
                )
            )
        return items
