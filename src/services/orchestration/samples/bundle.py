"""Đọc demo bundle đã export; chỉ phục vụ file nằm trong allow-list và đúng checksum."""

import logging
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.services.orchestration.artifacts import sha256_file
from src.services.orchestration.samples.models import DemoFile, DemoManifest, DemoSource

logger = logging.getLogger(__name__)
UNPUBLISHED_MARKER = ".unpublished"


class DemoUnavailableError(LookupError):
    """Deployment chưa có demo bundle (hoặc bundle hỏng); UI ẩn kịch bản demo."""


class DemoBundle:
    """Bundle read-only tại `<root>/manifest.json` + `<root>/files/<name>`."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def manifest(self) -> DemoManifest:
        """Đọc và validate manifest; thiếu/hỏng → DemoUnavailableError."""
        if (self.root / UNPUBLISHED_MARKER).exists():
            raise DemoUnavailableError("Mẫu đã được bỏ khỏi thư viện demo")
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
    """

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def bundles(self) -> dict[str, DemoBundle]:
        """Các bundle theo id; thư mục tên không an toàn bị bỏ qua."""
        if (self.root / "manifest.json").is_file():
            single = DemoBundle(self.root)
            try:
                return {single.manifest().demo_id: single}
            except DemoUnavailableError:
                return {}
        if not self.root.is_dir():
            return {}
        return {
            child.name: DemoBundle(child)
            for child in sorted(self.root.iterdir())
            if child.is_dir()
            and _SAMPLE_ID.fullmatch(child.name)
            and (child / "manifest.json").is_file()
            and not (child / UNPUBLISHED_MARKER).exists()
        }

    def bundle(self, sample_id: str) -> DemoBundle:
        """Bundle theo id; không có → DemoUnavailableError."""
        found = self.bundles().get(sample_id)
        if found is None:
            raise DemoUnavailableError("Không có video mẫu này")
        return found

    def unpublish(self, sample_id: str) -> None:
        """Gỡ mẫu khỏi thư viện công khai; giữ manifest và mọi artifact trên đĩa."""
        bundle = self.bundle(sample_id)
        if not bundle.root.is_relative_to(self.root):
            raise DemoUnavailableError("Mẫu không thuộc thư viện demo")
        bundle.manifest()
        (bundle.root / UNPUBLISHED_MARKER).touch()

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
