"""Nhận video upload theo stream vào artifact store và ghi danh sách upload bền vững.

Video được giữ nguyên bytes gốc (PRD FR-01: không làm mất input khi job lỗi). Tên
file người dùng chỉ để hiển thị; đường dẫn lưu trữ do hệ thống đặt.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import uuid4

from src.services.orchestration.artifacts import ArtifactResolver, StreamingPublication
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads.models import VIDEO_EXTENSIONS, UploadRecord


class UploadError(ValueError):
    """Upload không hợp lệ (định dạng, tên, dung lượng); message hiển thị được cho người dùng."""


class UploadNotFoundError(LookupError):
    """Không có upload với ID này."""


@dataclass
class PendingUpload:
    """Upload đang nhận bytes; chỉ thành UploadRecord sau `VideoUploadService.finish`."""

    upload_id: str
    original_name: str
    media_type: str
    publication: StreamingPublication


def _display_name(filename: str) -> str:
    """Bỏ thư mục client gửi kèm, giữ tên hiển thị ngắn và in được."""
    name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    name = re.sub(r"[\x00-\x1f]", "", name)[:255]
    if not name:
        raise UploadError("Tên file trống")
    return name


class VideoUploadService:
    """Mỗi request một instance; không giữ state ngoài DB và artifact store."""

    def __init__(self, database: RuntimeDatabase, resolver: ArtifactResolver, max_bytes: int) -> None:
        self.database = database
        self.resolver = resolver
        self.max_bytes = max_bytes

    def begin(self, filename: str) -> PendingUpload:
        """Kiểm đuôi file rồi mở publication; đích là `input/source<ext>` trong namespace upload."""
        name = _display_name(filename)
        suffix = PurePosixPath(name).suffix.lower()
        media_type = VIDEO_EXTENSIONS.get(suffix)
        if media_type is None:
            raise UploadError("Chỉ hỗ trợ video .mp4 hoặc .mov quay bằng camera di chuyển")
        upload_id = f"upload-{uuid4().hex[:12]}"
        uri = f"artifact://jobs/{upload_id}/input/source{suffix}"
        return PendingUpload(upload_id, name, media_type, StreamingPublication(self.resolver, uri, self.max_bytes))

    def finish(self, pending: PendingUpload) -> UploadRecord:
        """Commit bytes rồi ghi record; lỗi DB không để lại record trỏ tới file thiếu."""
        checksum = pending.publication.commit()
        record = UploadRecord(
            upload_id=pending.upload_id,
            original_name=pending.original_name,
            media_type=pending.media_type,
            size_bytes=pending.publication.size_bytes,
            checksum=checksum,
            artifact_uri=pending.publication.artifact_uri,
            received_at=datetime.now(UTC),
        )
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_uploads(upload_id, payload) VALUES (?, ?)",
                (record.upload_id, record.model_dump_json()),
            )
        return record

    def list(self) -> list[UploadRecord]:
        """Mới nhất trước để màn hình chọn video hiện upload vừa xong ở đầu."""
        with self.database.transaction() as tx:
            rows = tx.execute("SELECT payload FROM r2s_uploads").fetchall()
        records = [UploadRecord.model_validate_json(row[0]) for row in rows]
        return sorted(records, key=lambda record: record.received_at, reverse=True)

    def get(self, upload_id: str) -> UploadRecord:
        """Đọc một upload; ném UploadNotFoundError nếu không có."""
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_uploads WHERE upload_id=?", (upload_id,)).fetchone()
        if row is None:
            raise UploadNotFoundError(f"không tìm thấy upload: {upload_id}")
        return UploadRecord.model_validate_json(row[0])

    def link_project(self, upload_id: str, project_id: str) -> UploadRecord:
        """Ghi project đã tạo từ upload (một video có thể dựng nhiều scene)."""
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
            ).fetchone()
            if row is None:
                raise UploadNotFoundError(f"không tìm thấy upload: {upload_id}")
            record = UploadRecord.model_validate_json(row[0])
            if project_id in record.project_ids:
                raise RuntimeStateConflictError("project đã được gắn với upload này")
            updated = record.model_copy(update={"project_ids": [*record.project_ids, project_id]})
            tx.execute("UPDATE r2s_uploads SET payload=? WHERE upload_id=?", (updated.model_dump_json(), upload_id))
        return updated
