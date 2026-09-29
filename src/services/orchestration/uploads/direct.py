"""Upload video thẳng từ trình duyệt lên kho file (multipart presigned, ADR 0003).

Web UI và API không cõng bytes video: API chỉ mở phiên, cấp link PUT có hạn cho
từng phần, rồi ghép và **tự tính** checksum/kích thước từ kho file trước khi coi
video là đã nhận. Phiên lưu trong DB nên rớt mạng/đóng tab vẫn nối lại được.
"""

import math
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import uuid4

from src.services.orchestration.artifacts import ArtifactRemote, ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads.models import VIDEO_EXTENSIONS, UploadRecord, UploadSession
from src.services.orchestration.uploads.service import UploadError, UploadNotFoundError, display_name

#: Phần tối thiểu 16 MiB (S3 yêu cầu ≥ 5 MiB trừ phần cuối); tối đa 10.000 phần.
MIN_PART_BYTES = 16 * 1024 * 1024
MAX_PARTS = 10_000
#: Mỗi lần xin link tối đa bấy nhiêu phần để link không hết hạn khi upload chậm.
MAX_URLS_PER_REQUEST = 50


def plan_parts(size_bytes: int) -> tuple[int, int]:
    """Kích thước phần (bội số MiB) và số phần cho một file."""
    part_size = max(MIN_PART_BYTES, math.ceil(size_bytes / MAX_PARTS / (1024 * 1024)) * 1024 * 1024)
    return part_size, max(1, math.ceil(size_bytes / part_size))


class DirectUploadService:
    """Mỗi request một instance; state nằm trong DB và kho file."""

    def __init__(self, database: RuntimeDatabase, resolver: ArtifactResolver, max_bytes: int) -> None:
        if resolver.remote is None:
            raise UploadError("Deployment chưa cấu hình kho file; dùng upload qua API")
        self.database = database
        self.resolver = resolver
        self.remote: ArtifactRemote = resolver.remote
        self.max_bytes = max_bytes

    def begin(self, filename: str, size_bytes: int) -> UploadSession:
        """Kiểm tên/đuôi/dung lượng khai báo rồi mở multipart trên kho file."""
        name = display_name(filename)
        suffix = PurePosixPath(name).suffix.lower()
        media_type = VIDEO_EXTENSIONS.get(suffix)
        if media_type is None:
            raise UploadError("Chỉ hỗ trợ video .mp4 hoặc .mov quay bằng camera di chuyển")
        if size_bytes <= 0:
            raise UploadError("File rỗng")
        if size_bytes > self.max_bytes:
            raise UploadError(f"Video vượt giới hạn {self.max_bytes} bytes")
        upload_id = f"upload-{uuid4().hex[:12]}"
        uri = f"artifact://jobs/{upload_id}/input/source{suffix}"
        part_size, part_count = plan_parts(size_bytes)
        multipart_id = self.remote.begin_upload(self.resolver.relative_key(uri), media_type)
        session = UploadSession(
            upload_id=upload_id,
            original_name=name,
            media_type=media_type,
            size_bytes=size_bytes,
            part_size=part_size,
            part_count=part_count,
            artifact_uri=uri,
            multipart_id=multipart_id,
            status="UPLOADING",
            created_at=datetime.now(UTC),
        )
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_upload_sessions(upload_id, payload) VALUES (?, ?)",
                (upload_id, session.model_dump_json()),
            )
        return session

    def get(self, upload_id: str) -> UploadSession:
        """Đọc phiên; không có → UploadNotFoundError."""
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_upload_sessions WHERE upload_id=?", (upload_id,)).fetchone()
        if row is None:
            raise UploadNotFoundError(f"không tìm thấy phiên upload: {upload_id}")
        return UploadSession.model_validate_json(row[0])

    def uploaded_parts(self, session: UploadSession) -> list[int]:
        """Số thứ tự các phần đã lên kho file (để nối lại)."""
        if session.status != "UPLOADING":
            return []
        key = self.resolver.relative_key(session.artifact_uri)
        return sorted(part.part_number for part in self.remote.uploaded_parts(key, session.multipart_id))

    def part_urls(self, upload_id: str, part_numbers: list[int], expires_seconds: int) -> dict[int, str]:
        """Link PUT có hạn cho một nhóm phần của phiên đang upload."""
        session = self._require_status(upload_id, "UPLOADING")
        if not part_numbers or len(part_numbers) > MAX_URLS_PER_REQUEST:
            raise UploadError(f"Mỗi lần xin từ 1 đến {MAX_URLS_PER_REQUEST} phần")
        if any(number < 1 or number > session.part_count for number in part_numbers):
            raise UploadError("Số thứ tự phần không hợp lệ")
        key = self.resolver.relative_key(session.artifact_uri)
        return {
            number: self.remote.part_url(key, session.multipart_id, number, expires_seconds)
            for number in sorted(set(part_numbers))
        }

    def complete(self, upload_id: str, parts: list[tuple[int, str]]) -> UploadSession:
        """Ghép đủ các phần rồi chuyển sang VERIFYING; kiểm tra chạy riêng (`verify`)."""
        session = self._require_status(upload_id, "UPLOADING")
        numbers = sorted(number for number, _ in parts)
        if numbers != list(range(1, session.part_count + 1)):
            raise UploadError("Thiếu hoặc thừa phần; upload lại các phần còn thiếu")
        key = self.resolver.relative_key(session.artifact_uri)
        self.remote.complete_upload(key, session.multipart_id, sorted(parts))
        return self._update(session, status="VERIFYING")

    def verify(self, upload_id: str) -> UploadSession:
        """Server tự tính checksum/kích thước từ kho file rồi ghi UploadRecord (READY).

        Kích thước khác khai báo hoặc vượt giới hạn → FAILED và xóa object, vì bytes
        không khớp những gì người dùng đã chọn.
        """
        session = self._require_status(upload_id, "VERIFYING")
        key = self.resolver.relative_key(session.artifact_uri)
        checksum, size = self.remote.digest(key)
        if size != session.size_bytes or size > self.max_bytes:
            self.remote.delete(key)
            return self._update(session, status="FAILED", error="Kích thước video trên kho file khác khai báo")
        record = UploadRecord(
            upload_id=session.upload_id,
            original_name=session.original_name,
            media_type=session.media_type,
            size_bytes=size,
            checksum=checksum,
            artifact_uri=session.artifact_uri,
            received_at=datetime.now(UTC),
        )
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_upload_sessions WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
            ).fetchone()
            if row is None or UploadSession.model_validate_json(row[0]).status != "VERIFYING":
                raise RuntimeStateConflictError("phiên upload đã đổi trạng thái")
            tx.execute(
                "INSERT INTO r2s_uploads(upload_id, payload) VALUES (?, ?)",
                (record.upload_id, record.model_dump_json()),
            )
            ready = session.model_copy(update={"status": "READY"})
            tx.execute(
                "UPDATE r2s_upload_sessions SET payload=? WHERE upload_id=?", (ready.model_dump_json(), upload_id)
            )
        return ready

    def fail(self, upload_id: str, message: str) -> UploadSession:
        """Đánh dấu phiên FAILED với lời giải thích hiển thị được."""
        return self._update(self.get(upload_id), status="FAILED", error=message)

    def abort(self, upload_id: str) -> UploadSession:
        """Người dùng hủy upload dở: xóa các phần trên kho file."""
        session = self._require_status(upload_id, "UPLOADING")
        self.remote.abort_upload(self.resolver.relative_key(session.artifact_uri), session.multipart_id)
        return self._update(session, status="FAILED", error="Người dùng đã hủy upload")

    def _require_status(self, upload_id: str, status: str) -> UploadSession:
        session = self.get(upload_id)
        if session.status != status:
            raise RuntimeStateConflictError(f"phiên upload đang ở trạng thái {session.status}")
        return session

    def _update(self, session: UploadSession, **changes: object) -> UploadSession:
        """CAS theo trạng thái cũ để hai request không cùng chuyển trạng thái."""
        updated = session.model_copy(update=changes)
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_upload_sessions WHERE upload_id=?" + tx.lock_suffix(), (session.upload_id,)
            ).fetchone()
            if row is None or UploadSession.model_validate_json(row[0]).status != session.status:
                raise RuntimeStateConflictError("phiên upload đã đổi trạng thái")
            tx.execute(
                "UPDATE r2s_upload_sessions SET payload=? WHERE upload_id=?",
                (updated.model_dump_json(), session.upload_id),
            )
        return updated
