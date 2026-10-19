"""Nhận upload theo stream vào artifact store và ghi danh sách upload bền vững.

File được giữ nguyên bytes gốc (PRD FR-01: không làm mất input khi job lỗi). Tên
file người dùng chỉ để hiển thị; đường dẫn lưu trữ do hệ thống đặt. Loại đầu vào
(video, PLY 3DGS, ZIP PLY + COLMAP) nhận diện theo bytes trước khi ghi record (ADR 0004).
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from src.models.contracts.artifacts import ArtifactDataClass
from src.models.contracts.manifests import InputFile
from src.models.contracts.video_preparation import ClientVideoPreparationManifest, ServerVideoPreparationVerification
from src.services.orchestration.artifacts import ArtifactResolver, StreamingPublication
from src.services.orchestration.auth.models import Actor
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads.assembly_models import StagedInputUploadRecord
from src.services.orchestration.uploads.models import (
    ASSEMBLY_UPLOAD_EXTENSIONS,
    KIND_MEDIA_TYPES,
    UNSUPPORTED_EXTENSION,
    UPLOAD_EXTENSIONS,
    UploadRecord,
)
from src.services.reconstruction import InputDetection, InputRejectedError, detect_stream
from src.services.reconstruction.inputs.input_probe import classify_upload as probe_input_upload

#: ZIP giải nén tối đa gấp đôi giới hạn upload: PLY/ảnh nén kém nên file thật không
#: vượt; chặn zip bomb mà không cần đọc hết nội dung.
ZIP_EXPANSION_LIMIT = 2


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


def display_name(filename: str) -> str:
    """Bỏ thư mục client gửi kèm, giữ tên hiển thị ngắn và in được."""
    name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    name = re.sub(r"[\x00-\x1f]", "", name)[:255]
    if not name:
        raise UploadError("Tên file trống")
    return name


def classify_upload(stream: BinaryIO, size_bytes: int, media_type: str, max_bytes: int) -> InputDetection:
    """Nhận diện loại theo bytes; đuôi file phải khớp nội dung để người dùng không nhầm."""
    try:
        detection = detect_stream(stream, size_bytes, max_bytes * ZIP_EXPANSION_LIMIT)
    except InputRejectedError as error:
        raise UploadError(str(error)) from error
    if media_type not in KIND_MEDIA_TYPES[detection.kind]:
        raise UploadError(
            "Đuôi file không khớp nội dung; đổi đúng đuôi (.mp4/.mov, .ply, .sog, .pcd hoặc .zip) rồi tải lại"
        )
    return detection


class VideoUploadService:
    """Mỗi request một instance; không giữ state ngoài DB và artifact store."""

    def __init__(self, database: RuntimeDatabase, resolver: ArtifactResolver, max_bytes: int) -> None:
        self.database = database
        self.resolver = resolver
        self.max_bytes = max_bytes

    def begin(self, filename: str) -> PendingUpload:
        """Kiểm đuôi file rồi mở publication; đích là `input/source<ext>` trong namespace upload."""
        name = display_name(filename)
        suffix = PurePosixPath(name).suffix.lower()
        media_type = UPLOAD_EXTENSIONS.get(suffix)
        if media_type is None:
            raise UploadError(UNSUPPORTED_EXTENSION)
        upload_id = f"upload-{uuid4().hex[:12]}"
        uri = f"artifact://jobs/{upload_id}/input/source{suffix}"
        return PendingUpload(upload_id, name, media_type, StreamingPublication(self.resolver, uri, self.max_bytes))

    def begin_assembly(self, filename: str) -> PendingUpload:
        """Begin a generic file upload for content-probed input assemblies."""
        name = display_name(filename)
        suffix = PurePosixPath(name).suffix.lower()
        media_type = ASSEMBLY_UPLOAD_EXTENSIONS.get(suffix, "application/octet-stream")
        upload_id = f"upload-{uuid4().hex[:12]}"
        uri = f"artifact://jobs/{upload_id}/input/source{suffix or '.bin'}"
        return PendingUpload(upload_id, name, media_type, StreamingPublication(self.resolver, uri, self.max_bytes))

    def finish(
        self, pending: PendingUpload, uploaded_by: Actor | None = None, *, temporary: bool = False
    ) -> UploadRecord:
        """Nhận diện loại, commit bytes rồi ghi record (kèm người tải lên); file sai loại không được lưu."""
        publication = pending.publication
        with publication.staged_path().open("rb") as stream:
            detection = classify_upload(stream, publication.size_bytes, pending.media_type, self.max_bytes)
        checksum = publication.commit()
        record = UploadRecord(
            upload_id=pending.upload_id,
            original_name=pending.original_name,
            media_type=pending.media_type,
            size_bytes=pending.publication.size_bytes,
            checksum=checksum,
            artifact_uri=pending.publication.artifact_uri,
            received_at=datetime.now(UTC),
            input_kind=detection.kind,
            detection=detection,
            uploaded_by=uploaded_by,
        )
        with self.database.transaction(write=True) as tx:
            if temporary:
                from src.services.orchestration.uploads.temporary import register_temporary

                register_temporary(tx, record.upload_id, uploaded_by.user_id if uploaded_by else "anonymous")
            tx.execute(
                "INSERT INTO r2s_uploads(upload_id, payload) VALUES (?, ?)",
                (record.upload_id, record.model_dump_json()),
            )
        return record

    def finish_assembly(
        self, pending: PendingUpload, uploaded_by: Actor | None = None, *, temporary: bool = False
    ) -> StagedInputUploadRecord:
        """Probe and store generic assembly bytes without weakening legacy upload rules."""
        publication = pending.publication
        path = publication.staged_path()
        size_bytes = publication.size_bytes
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum = f"sha256:{digest.hexdigest()}"
        source_file = InputFile(
            original_name=pending.original_name,
            media_type=pending.media_type,
            size_bytes=size_bytes,
            checksum=checksum,
            artifact_uri=publication.artifact_uri,
            data_class=ArtifactDataClass.PRODUCT_INPUT,
        )
        classified = probe_input_upload(
            source_file,
            pending.upload_id,
            pending.upload_id,
            path,
            max_uncompressed_bytes=self.max_bytes * ZIP_EXPANSION_LIMIT,
        )
        legacy: UploadRecord | None = None
        try:
            with path.open("rb") as source:
                detection = classify_upload(source, size_bytes, pending.media_type, self.max_bytes)
        except UploadError:
            detection = None
        else:
            legacy = UploadRecord(
                upload_id=pending.upload_id,
                original_name=pending.original_name,
                media_type=pending.media_type,
                size_bytes=size_bytes,
                checksum=checksum,
                artifact_uri=publication.artifact_uri,
                received_at=datetime.now(UTC),
                input_kind=detection.kind,
                detection=detection,
                uploaded_by=uploaded_by,
            )
        committed_checksum = publication.commit()
        if committed_checksum != checksum:
            raise RuntimeStateConflictError("Upload bytes changed between assembly probe and publication")
        staged = StagedInputUploadRecord(
            upload_id=pending.upload_id,
            source_file=source_file,
            staged_files=list(classified.files),
            probes=list(classified.probes),
            uploaded_by=uploaded_by,
            received_at=datetime.now(UTC),
        )
        with self.database.transaction(write=True) as tx:
            if temporary:
                from src.services.orchestration.uploads.temporary import register_temporary

                register_temporary(tx, staged.upload_id, uploaded_by.user_id if uploaded_by else "anonymous")
            if legacy is not None:
                tx.execute(
                    "INSERT INTO r2s_uploads(upload_id,payload) VALUES (?,?)",
                    (legacy.upload_id, legacy.model_dump_json()),
                )
            tx.execute(
                "INSERT INTO r2s_input_uploads(upload_id,payload) VALUES (?,?)",
                (staged.upload_id, staged.model_dump_json()),
            )
        return staged

    def stage_for_assembly(self, upload_id: str) -> StagedInputUploadRecord:
        """Adopt an existing verified upload without copying its bytes into a second artifact."""
        upload = self.get(upload_id)
        source_file = InputFile(
            original_name=upload.original_name,
            media_type=upload.media_type,
            size_bytes=upload.size_bytes,
            checksum=upload.checksum,
            artifact_uri=upload.artifact_uri,
            data_class=ArtifactDataClass.PRODUCT_INPUT,
        )
        path = self.resolver.require_uri(source_file.artifact_uri, source_file.checksum)
        classified = probe_input_upload(
            source_file,
            upload.upload_id,
            upload.upload_id,
            path,
            max_uncompressed_bytes=self.max_bytes * ZIP_EXPANSION_LIMIT,
        )
        candidate = StagedInputUploadRecord(
            upload_id=upload.upload_id,
            source_file=source_file,
            staged_files=list(classified.files),
            probes=list(classified.probes),
            uploaded_by=upload.uploaded_by,
            received_at=upload.received_at,
            project_ids=upload.project_ids,
        )
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_input_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
            ).fetchone()
            if row is not None:
                existing = StagedInputUploadRecord.model_validate_json(row[0])
                if (
                    existing.source_file != candidate.source_file
                    or existing.staged_files != candidate.staged_files
                    or existing.probes != candidate.probes
                    or existing.uploaded_by != candidate.uploaded_by
                ):
                    raise RuntimeStateConflictError("Staged input upload differs from its verified source upload")
                return existing
            tx.execute(
                "INSERT INTO r2s_input_uploads(upload_id,payload) VALUES (?,?)",
                (candidate.upload_id, candidate.model_dump_json()),
            )
        return candidate

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

    def discard_unlinked(self, upload_id: str, *, expected_checksum: str) -> bool:
        """Gỡ một upload do server vừa tạo mà chưa gắn project (dọn khi lần chạy không thành).

        Chỉ gỡ khi bản ghi còn đúng checksum đã khai và chưa gắn project nào, nên không thể xoá nhầm dữ liệu
        đang dùng. Gỡ cả file cục bộ lẫn bản trên kho từ xa (nếu có). Trả về True khi đã gỡ.
        """
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
            ).fetchone()
            if row is None:
                return False
            record = UploadRecord.model_validate_json(row[0])
            if record.project_ids or record.checksum != expected_checksum:
                return False
            tx.execute("DELETE FROM r2s_uploads WHERE upload_id=?", (upload_id,))
        path = self.resolver.resolve(record.artifact_uri)
        path.unlink(missing_ok=True)
        remote = self.resolver.remote
        if remote is not None:
            # Bản đã đẩy lên kho từ xa lúc commit: không gỡ thì còn một bản sao dữ liệu người dùng không ai quản.
            remote.delete(self.resolver.relative_key(record.artifact_uri))
        return True

    def save_video_preparation_manifest(self, upload_id: str, manifest: ClientVideoPreparationManifest) -> UploadRecord:
        """Store a client declaration as pending only; it is not server evidence."""
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
            ).fetchone()
            if row is None:
                raise UploadNotFoundError(f"không tìm thấy upload: {upload_id}")
            current = UploadRecord.model_validate_json(row[0])
            if current.input_kind != "rgb_video" or current.media_type != "video/mp4":
                raise UploadError("Nén video chỉ áp dụng cho file MP4 đã nhận diện là video RGB")
            if current.project_ids:
                raise RuntimeStateConflictError("Không thể đổi provenance sau khi upload đã gắn với scene")
            if current.video_preparation is not None and current.video_preparation.client_manifest != manifest:
                raise RuntimeStateConflictError("Video preparation đã được xác minh và không thể thay đổi")
            updated = current.model_copy(update={"video_preparation_manifest": manifest})
            tx.execute("UPDATE r2s_uploads SET payload=? WHERE upload_id=?", (updated.model_dump_json(), upload_id))
        return updated

    def save_video_preparation_verification(
        self, upload_id: str, verification: ServerVideoPreparationVerification
    ) -> UploadRecord:
        """Persist immutable verification only if the uploaded bytes and declaration still match."""
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
            ).fetchone()
            if row is None:
                raise UploadNotFoundError(f"không tìm thấy upload: {upload_id}")
            current = UploadRecord.model_validate_json(row[0])
            if current.video_preparation_manifest != verification.client_manifest:
                raise RuntimeStateConflictError("Video preparation declaration changed during verification")
            if (
                current.checksum != verification.uploaded_checksum
                or current.size_bytes != verification.uploaded_size_bytes
            ):
                raise UploadError("Video preparation identity differs from the server upload record")
            if verification.frame_map_ref.job_id != upload_id:
                raise UploadError("Video frame map belongs to another upload")
            if current.video_preparation is not None:
                if current.video_preparation != verification:
                    raise RuntimeStateConflictError("Upload đã có một frame map khác được xác minh")
                return current
            updated = current.model_copy(update={"video_preparation": verification})
            tx.execute("UPDATE r2s_uploads SET payload=? WHERE upload_id=?", (updated.model_dump_json(), upload_id))
        return updated

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
