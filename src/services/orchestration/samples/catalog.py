"""Catalog thư viện mẫu demo: cơ sở dữ liệu cộng kho file là nguồn sự thật, đĩa của API chỉ là bộ đệm.

Một mẫu được xuất bản khi mọi file của nó đã nằm trong kho file (key `<prefix>/<sample_id>/<đường dẫn>`) và có dòng
`r2s_demo_samples` ở trạng thái `published`. Bỏ và thêm lại chỉ đổi trạng thái dòng đó. Lúc khởi động API đối chiếu đĩa
với catalog và tải lại file thiếu hoặc sai, không bao giờ từ chối chạy vì đĩa lệch.
"""

import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from src.config import Settings
from src.services.orchestration.artifacts import ObjectStore, sha256_file
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.samples.bundle import DemoLibrary, DemoUnavailableError
from src.services.orchestration.samples.models import DemoManifest
from src.services.orchestration.storage import artifact_remote

logger = logging.getLogger(__name__)
SampleState = Literal["published", "unpublished"]


class SampleFile(BaseModel):
    """Một file trong bundle, đường dẫn tương đối kiểu posix tính từ thư mục mẫu."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    size_bytes: int
    checksum: str


class SampleRecord(BaseModel):
    """Dòng catalog của một mẫu: trạng thái, job nguồn và danh sách file đã kiểm."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str
    state: SampleState
    job_id: str | None
    manifest_checksum: str
    files: list[SampleFile]
    published_by: str | None
    published_at: AwareDatetime
    updated_at: AwareDatetime


def inventory(root: Path) -> list[SampleFile]:
    """Mọi file thường dưới `root` (bỏ phần tên bắt đầu bằng '.'), sắp theo đường dẫn; symlink là lỗi."""
    files: list[SampleFile] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Demo bundle contains a symlink: {relative.as_posix()}")
        if path.is_file():
            files.append(
                SampleFile(path=relative.as_posix(), size_bytes=path.stat().st_size, checksum=sha256_file(path))
            )
    return files


def object_key(prefix: str, sample_id: str, relative: str) -> str:
    return f"{prefix.strip('/')}/{sample_id}/{relative}"


class DemoCatalog:
    """Đọc/ghi bảng `r2s_demo_samples`."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.database = database

    @staticmethod
    def _parse(row: tuple) -> SampleRecord:
        sample_id, state, job_id, manifest_checksum, published_by, published_at, updated_at, payload = row
        return SampleRecord(
            sample_id=sample_id,
            state=state,
            job_id=job_id,
            manifest_checksum=manifest_checksum,
            files=[SampleFile.model_validate(item) for item in json.loads(payload)["files"]],
            published_by=published_by,
            published_at=datetime.fromisoformat(published_at),
            updated_at=datetime.fromisoformat(updated_at),
        )

    _COLUMNS = "sample_id,state,job_id,manifest_checksum,published_by,published_at,updated_at,payload"

    def get(self, sample_id: str) -> SampleRecord | None:
        with self.database.transaction() as tx:
            row = tx.execute(f"SELECT {self._COLUMNS} FROM r2s_demo_samples WHERE sample_id=?", (sample_id,)).fetchone()
        return self._parse(row) if row is not None else None

    def records(self, state: SampleState | None = None) -> list[SampleRecord]:
        with self.database.transaction() as tx:
            if state is None:
                rows = tx.execute(f"SELECT {self._COLUMNS} FROM r2s_demo_samples ORDER BY sample_id").fetchall()
            else:
                rows = tx.execute(
                    f"SELECT {self._COLUMNS} FROM r2s_demo_samples WHERE state=? ORDER BY sample_id", (state,)
                ).fetchall()
        return [self._parse(row) for row in rows]

    def published_ids(self) -> set[str]:
        with self.database.transaction() as tx:
            rows = tx.execute("SELECT sample_id FROM r2s_demo_samples WHERE state='published'").fetchall()
        return {row[0] for row in rows}

    def is_published(self, sample_id: str) -> bool:
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT 1 FROM r2s_demo_samples WHERE sample_id=? AND state='published'", (sample_id,)
            ).fetchone()
        return row is not None

    def by_job(self, job_id: str, *, state: SampleState = "published") -> SampleRecord | None:
        """Mẫu mới nhất của một job ở trạng thái đã cho."""
        with self.database.transaction() as tx:
            row = tx.execute(
                f"SELECT {self._COLUMNS} FROM r2s_demo_samples WHERE job_id=? AND state=? "
                "ORDER BY updated_at DESC, sample_id LIMIT 1",
                (job_id, state),
            ).fetchone()
        return self._parse(row) if row is not None else None

    def save(self, record: SampleRecord) -> None:
        payload = json.dumps({"files": [file.model_dump() for file in record.files]}, sort_keys=True)
        with self.database.transaction(write=True) as tx:
            tx.execute(
                f"INSERT INTO r2s_demo_samples({self._COLUMNS}) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(sample_id) DO UPDATE SET state=excluded.state, job_id=excluded.job_id, "
                "manifest_checksum=excluded.manifest_checksum, published_by=excluded.published_by, "
                "published_at=excluded.published_at, updated_at=excluded.updated_at, payload=excluded.payload",
                (
                    record.sample_id,
                    record.state,
                    record.job_id,
                    record.manifest_checksum,
                    record.published_by,
                    record.published_at.isoformat(),
                    record.updated_at.isoformat(),
                    payload,
                ),
            )

    def set_state(self, sample_id: str, state: SampleState) -> SampleRecord:
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            changed = tx.execute(
                "UPDATE r2s_demo_samples SET state=?, updated_at=? WHERE sample_id=?",
                (state, now.isoformat(), sample_id),
            ).rowcount
        if changed != 1:
            raise DemoUnavailableError("Không có video mẫu này")
        record = self.get(sample_id)
        assert record is not None
        return record


def upload_bundle(store: ObjectStore, prefix: str, sample_id: str, root: Path, files: list[SampleFile]) -> int:
    """Đẩy từng file lên kho (bất biến): đã có cùng checksum thì bỏ qua, khác thì lỗi. Trả số object vừa đẩy."""

    def put(file: SampleFile) -> int:
        key = object_key(prefix, sample_id, file.path)
        existing = store.head(key)
        if existing is not None and existing.checksum is not None:
            if existing.checksum != file.checksum:
                raise ValueError("Immutable demo object already exists with different bytes")
            return 0
        # Chưa có, hoặc object cũ không ghi checksum trong metadata: đẩy lại cùng nội dung để lần sau so được.
        store.put_file(key, root / file.path, file.checksum)
        return 1

    with ThreadPoolExecutor(max_workers=4) as executor:
        return sum(executor.map(put, files))


def record_from_disk(
    root: Path, sample_id: str, *, state: SampleState, actor: str | None, job_id: str | None = None
) -> SampleRecord:
    """Dòng catalog dựng từ bundle trên đĩa (chưa ghi, chưa đẩy lên kho). Mã mẫu là tên thư mục; manifest phải hợp lệ."""
    try:
        manifest = DemoManifest.model_validate_json((root / "manifest.json").read_bytes())
    except ValueError as error:
        raise ValueError(f"Demo bundle manifest is invalid: {error}") from error
    if job_id is None:
        job_id = manifest.provenance.get("job_id")
    now = datetime.now(UTC)
    return SampleRecord(
        sample_id=sample_id,
        state=state,
        job_id=job_id,
        manifest_checksum=sha256_file(root / "manifest.json"),
        files=inventory(root),
        published_by=actor,
        published_at=now,
        updated_at=now,
    )


def register_bundle(
    settings: Settings,
    catalog: DemoCatalog,
    root: Path,
    *,
    actor: str | None,
    state: SampleState = "published",
    job_id: str | None = None,
) -> SampleRecord:
    """Kiểm kê bundle trên đĩa, đẩy lên kho file (nếu có), rồi ghi dòng catalog. Chỉ ghi dòng khi kho đã có đủ file."""
    record = record_from_disk(root, root.name, state=state, actor=actor, job_id=job_id)
    remote = artifact_remote(settings)
    if remote is not None:
        upload_bundle(remote.store, settings.product_demo_object_prefix, record.sample_id, root, record.files)
    catalog.save(record)
    return record


def library(settings: Settings) -> DemoLibrary:
    """Thư viện mẫu của deployment: thư mục đệm trên đĩa gắn với catalog trong DB của `settings`."""
    return DemoLibrary(settings.product_demo_dir, catalog=DemoCatalog(RuntimeDatabase(settings.database_url)))


class SyncReport(BaseModel):
    """Kết quả đối chiếu đĩa với catalog lúc khởi động."""

    model_config = ConfigDict(extra="forbid")

    verified: list[str] = []
    repaired: list[str] = []
    broken: list[str] = []


def import_library(settings: Settings, catalog: DemoCatalog, *, actor: str | None = "import") -> list[str]:
    """Đưa bundle đang có trên đĩa mà catalog chưa biết vào catalog (và kho file).

    Bundle trên đĩa là do bản phát hành đã ghim hoặc người vận hành đặt vào, nên được coi là đang công khai; trừ khi
    thư mục mang file `.unpublished` của cơ chế cũ. Bảng `r2s_demo_unpublished` cũ không được đọc: trạng thái của nó
    từng lệch với đĩa (lý do có catalog này), Reviewer bỏ lại trong Studio nếu cần.
    """
    root = settings.product_demo_dir.expanduser()
    if not root.is_dir():
        return []
    registered: list[str] = []
    for child in sorted(root.iterdir()):
        if (
            child.name.startswith(".")
            or not child.is_dir()
            or child.is_symlink()
            or not (child / "manifest.json").is_file()
            or catalog.get(child.name) is not None
        ):
            continue
        state: SampleState = "unpublished" if (child / ".unpublished").exists() else "published"
        try:
            register_bundle(settings, catalog, child, actor=actor, state=state)
        except (OSError, ValueError) as error:
            logger.warning("Bỏ qua bundle không nhập được %s: %s", child.name, error)
            continue
        registered.append(child.name)
    return registered


def _healthy(path: Path, file: SampleFile) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size == file.size_bytes
        and sha256_file(path) == file.checksum
    )


def _fetch(store: ObjectStore, key: str, destination: Path, file: SampleFile) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=destination.parent, prefix=".repair-")
    os.close(descriptor)
    temporary = Path(name)
    try:
        store.get_file(key, temporary)
        if sha256_file(temporary) != file.checksum:
            raise ValueError(f"Demo object checksum mismatch: {key}")
        if destination.is_symlink() or destination.is_dir():
            raise ValueError(f"Demo cache path is not a regular file: {destination}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def sync_library(settings: Settings, catalog: DemoCatalog) -> SyncReport:
    """Mỗi mẫu đã xuất bản: file thiếu hoặc sai được tải lại từ kho; không tải được thì ghi nhận và bỏ qua."""
    report = SyncReport()
    root = settings.product_demo_dir.expanduser()
    remote = artifact_remote(settings)
    prefix = settings.product_demo_object_prefix
    for record in catalog.records(state="published"):
        sample_root = root / record.sample_id
        damaged = [file for file in record.files if not _healthy(sample_root / file.path, file)]
        if not damaged:
            report.verified.append(record.sample_id)
            continue
        if remote is None:
            logger.warning("Mẫu %s thiếu %d file và không có kho file để tải lại", record.sample_id, len(damaged))
            report.broken.append(record.sample_id)
            continue
        try:
            for file in damaged:
                _fetch(remote.store, object_key(prefix, record.sample_id, file.path), sample_root / file.path, file)
        except Exception as error:  # noqa: BLE001 - một mẫu hỏng không được làm sập API
            logger.warning("Không tải lại được mẫu %s: %s", record.sample_id, error)
            report.broken.append(record.sample_id)
            continue
        logger.info("Đã tải lại %d file của mẫu %s", len(damaged), record.sample_id)
        report.repaired.append(record.sample_id)
    return report


def _has_bundle(root: Path) -> bool:
    return root.is_dir() and any((child / "manifest.json").is_file() for child in root.iterdir() if child.is_dir())


def prepare_library(settings: Settings, database: RuntimeDatabase) -> SyncReport:
    """Lúc khởi động: gieo từ bản phát hành đã ghim (một lần), nhập bundle lạ trên đĩa, rồi đối chiếu và sửa."""
    from src.services.orchestration.samples.release import bootstrap_library

    catalog = DemoCatalog(database)
    root = settings.product_demo_dir.expanduser()
    if settings.product_demo_archive_key and not catalog.records() and not _has_bundle(root):
        bootstrap_library(settings)
    imported = import_library(settings, catalog)
    if imported:
        logger.info("Đã nhập %d mẫu từ đĩa vào catalog: %s", len(imported), ", ".join(imported))
    report = sync_library(settings, catalog)
    if settings.product_demo_required and not (report.verified or report.repaired):
        # Không chết: API vẫn phục vụ việc khác; `/health/ready` báo "waiting" cho tới khi có mẫu dùng được.
        logger.error("Demo library is required but no published sample is usable (broken=%s)", report.broken)
    return report
