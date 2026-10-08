"""Scene 3DGS người dùng tải lên — chỉ xem/chỉnh sửa (ADR 0004 §3, gói 5), ranh giới EX-PRODUCT.

Không phải job: không qua REC-06/05 và không tạo ReconstructionPreview (contract yêu cầu
camera + Brush). Bản ghi nằm ở `r2s_imports`; bytes gốc giữ nguyên trong upload, bản xem
là SOG nén bằng splat-transform qua port REC, publish bất biến theo nội dung.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.input_assembly import GaussianViewFormat
from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import ArtifactResolver, StreamingPublication
from src.services.orchestration.auth.models import DisplayName, Role
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads.models import UploadRecord
from src.services.reconstruction import extract_member, package_splat

logger = logging.getLogger(__name__)

ImportStatus = Literal["PACKAGING", "READY", "FAILED"]
ImportOperationStatus = Literal["QUEUED", "WAITING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
_ANONYMOUS_REQUESTER = "__anonymous__"
_IMPORT_LEASE_SECONDS = 300


class ImportOperationRecord(BaseModel):
    """Durable scheduling and packaging record; never shares reconstruction job state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    operation_id: str
    import_id: str
    upload_id: str
    upload_checksum: str
    packaging_config_checksum: str
    gpu_index: int | None = None
    status: ImportOperationStatus
    attempt: int = Field(ge=0)
    owner_id: str | None = None
    fencing_token: int = Field(ge=0)
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    delivery_ref: ProductArtifactRef | None = None
    error: str | None = None

    def projection(self) -> ImportOperationProjection:
        return ImportOperationProjection(
            operation_id=self.operation_id,
            status=self.status,
            attempt=self.attempt,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ImportOperationProjection(BaseModel):
    """Safe public subset of the durable operation record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    status: ImportOperationStatus
    attempt: int = Field(ge=0)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ImportedScene(BaseModel):
    """Một scene import; `delivery_ref` là SOG để trình duyệt nạp."""

    model_config = ConfigDict(extra="forbid")

    import_id: str
    upload_id: str
    name: str = Field(min_length=1, max_length=200)
    input_kind: GaussianViewFormat
    status: ImportStatus
    operation: ImportOperationProjection | None = Field(default=None, exclude_if=lambda value: value is None)
    delivery_ref: ProductArtifactRef | None = None
    error: str | None = None
    created_at: datetime
    created_by: str | None = None
    #: Tên người tạo lúc import (chụp lại để vẫn hiện được khi tài khoản đổi tên); None với record cũ.
    created_by_name: DisplayName | None = None
    #: Optional creation-time snapshot; absent on legacy imports and never backfilled from current role.
    created_by_role: Role | None = Field(default=None, exclude_if=lambda value: value is None)


class SceneImportError(ValueError):
    """Đầu vào/trạng thái import không hợp lệ; message hiển thị được."""


class ImportNotFoundError(LookupError):
    """Không có import với ID này."""


class ImportService:
    """Mỗi request một instance; state nằm ở DB + artifact store."""

    def __init__(self, database: RuntimeDatabase, resolver: ArtifactResolver, workspace_root: Path) -> None:
        self.database = database
        self.resolver = resolver
        self.workspace_root = workspace_root
        self._legacy_recovery_done = False

    @staticmethod
    def _config_checksum(input_kind: GaussianViewFormat, gpu_index: int | None) -> str:
        settings = {
            "schema_version": "1.0",
            "source_format": input_kind.value,
            "target_format": "gaussian_sog_v2",
            "processor": "splat-transform" if input_kind != GaussianViewFormat.SOG else "byte-preserving-copy",
            "sh_iterations": 10 if input_kind != GaussianViewFormat.SOG else None,
            "gpu_index": gpu_index if input_kind != GaussianViewFormat.SOG else None,
        }
        digest = hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return f"sha256:{digest}"

    @staticmethod
    def _request_fingerprint(upload_id: str, name: str) -> str:
        encoded = json.dumps({"upload_id": upload_id, "name": name}, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _new_operation(
        record: ImportedScene,
        upload: UploadRecord,
        gpu_index: int | None,
    ) -> ImportOperationRecord:
        now = datetime.now(UTC)
        return ImportOperationRecord(
            operation_id=f"import-op-{uuid4().hex[:16]}",
            import_id=record.import_id,
            upload_id=upload.upload_id,
            upload_checksum=upload.checksum,
            packaging_config_checksum=ImportService._config_checksum(record.input_kind, gpu_index),
            gpu_index=gpu_index,
            status="QUEUED",
            attempt=0,
            owner_id=None,
            fencing_token=0,
            lease_expires_at=None,
            heartbeat_at=None,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _with_operation(record: ImportedScene, operation_payload: str | None) -> ImportedScene:
        if operation_payload is None:
            return record
        operation = ImportOperationRecord.model_validate_json(operation_payload)
        return record.model_copy(update={"operation": operation.projection()})

    def create(
        self,
        upload: UploadRecord,
        name: str,
        created_by: str | None,
        created_by_name: str | None = None,
        created_by_role: Role | None = None,
        *,
        idempotency_key: str | None = None,
        gpu_index: int | None = None,
    ) -> ImportedScene:
        """Ghi scene và operation QUEUED trong cùng transaction; chỉ nhận nguồn 3DGS đã nhận diện."""
        try:
            input_kind = GaussianViewFormat(upload.input_kind)
        except ValueError as error:
            raise SceneImportError(
                "Chỉ file 3DGS (.ply, .sog hoặc .zip PLY + COLMAP) mới import thành scene"
            ) from error
        if input_kind == GaussianViewFormat.SOG and (upload.detection is None or upload.detection.sog is None):
            raise SceneImportError("Upload SOG thiếu bằng chứng metadata đã xác minh")
        if idempotency_key is not None and (not idempotency_key.strip() or len(idempotency_key) > 128):
            raise SceneImportError("Idempotency-Key phải dài 1..128 ký tự")
        normalized_name = name.strip() or upload.original_name
        fingerprint = self._request_fingerprint(upload.upload_id, normalized_name)
        requester_id = created_by or _ANONYMOUS_REQUESTER
        record = ImportedScene(
            import_id=f"import-{uuid4().hex[:12]}",
            upload_id=upload.upload_id,
            name=normalized_name,
            input_kind=input_kind,
            status="PACKAGING",
            created_at=datetime.now(UTC),
            created_by=created_by,
            created_by_name=created_by_name,
            created_by_role=created_by_role,
        )
        operation = self._new_operation(record, upload, gpu_index)
        with self.database.transaction(write=True) as tx:
            if idempotency_key is not None:
                existing = tx.execute(
                    "SELECT import_id, request_fingerprint, payload FROM r2s_import_operations "
                    "WHERE requester_id=? AND idempotency_key=?",
                    (requester_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if existing[1] != fingerprint:
                        raise SceneImportError("Idempotency-Key đã được dùng cho một yêu cầu import khác")
                    existing_import = tx.execute(
                        "SELECT payload FROM r2s_imports WHERE import_id=?", (existing[0],)
                    ).fetchone()
                    if existing_import is None:
                        raise RuntimeStateConflictError("idempotency record thiếu scene import")
                    return self._with_operation(ImportedScene.model_validate_json(existing_import[0]), existing[2])
            tx.execute(
                "INSERT INTO r2s_imports(import_id, upload_id, payload) VALUES (?, ?, ?)",
                (record.import_id, record.upload_id, record.model_dump_json()),
            )
            cursor = tx.execute(
                "INSERT INTO r2s_import_operations "
                "(operation_id, import_id, status, attempt, requester_id, idempotency_key, request_fingerprint, "
                "created_at, updated_at, owner_id, fencing_token, lease_expires_at, heartbeat_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (
                    operation.operation_id,
                    operation.import_id,
                    operation.status,
                    operation.attempt,
                    requester_id,
                    idempotency_key,
                    fingerprint,
                    operation.created_at.isoformat(),
                    operation.updated_at.isoformat(),
                    operation.owner_id,
                    operation.fencing_token,
                    None,
                    None,
                    operation.model_dump_json(),
                ),
            )
            if cursor.rowcount == 0:
                tx.execute("DELETE FROM r2s_imports WHERE import_id=?", (record.import_id,))
                if idempotency_key is None:
                    raise RuntimeStateConflictError("không ghi được import operation")
                existing = tx.execute(
                    "SELECT import_id, request_fingerprint, payload FROM r2s_import_operations "
                    "WHERE requester_id=? AND idempotency_key=?",
                    (requester_id, idempotency_key),
                ).fetchone()
                existing_import = (
                    tx.execute("SELECT payload FROM r2s_imports WHERE import_id=?", (existing[0],)).fetchone()
                    if existing is not None
                    else None
                )
                if existing is None or existing_import is None:
                    raise RuntimeStateConflictError("idempotency race left no durable import")
                if existing[1] != fingerprint:
                    raise SceneImportError("Idempotency-Key đã được dùng cho một yêu cầu import khác")
                return self._with_operation(ImportedScene.model_validate_json(existing_import[0]), existing[2])
        return self._with_operation(record, operation.model_dump_json())

    def get(self, import_id: str) -> ImportedScene:
        """Đọc một import; không có → ImportNotFoundError."""
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT i.payload, o.payload FROM r2s_imports i LEFT JOIN r2s_import_operations o "
                "ON o.import_id=i.import_id WHERE i.import_id=?",
                (import_id,),
            ).fetchone()
        if row is None:
            raise ImportNotFoundError(f"không tìm thấy scene import: {import_id}")
        return self._with_operation(ImportedScene.model_validate_json(row[0]), row[1])

    def list(self) -> list[ImportedScene]:
        """Mới nhất trước."""
        with self.database.transaction() as tx:
            rows = tx.execute(
                "SELECT i.payload, o.payload FROM r2s_imports i LEFT JOIN r2s_import_operations o "
                "ON o.import_id=i.import_id"
            ).fetchall()
        records = [self._with_operation(ImportedScene.model_validate_json(row[0]), row[1]) for row in rows]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    @staticmethod
    def _checksum_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1 << 20):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def _operation_record(self, import_id: str) -> ImportOperationRecord:
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_import_operations WHERE import_id=?", (import_id,)).fetchone()
        if row is None:
            raise RuntimeStateConflictError("scene import chưa có durable operation")
        return ImportOperationRecord.model_validate_json(row[0])

    def _finish(
        self,
        record: ImportedScene,
        operation: ImportOperationRecord,
        *,
        status: Literal["READY", "FAILED"],
        delivery_ref: ProductArtifactRef | None = None,
        error: str | None = None,
    ) -> ImportedScene:
        now = datetime.now(UTC)
        operation_status: ImportOperationStatus = "SUCCEEDED" if status == "READY" else "FAILED"
        updated_operation = operation.model_copy(
            update={
                "status": operation_status,
                "owner_id": None,
                "lease_expires_at": None,
                "heartbeat_at": now,
                "updated_at": now,
                "delivery_ref": delivery_ref,
                "error": error,
            }
        )
        updated = record.model_copy(
            update={
                "status": status,
                "delivery_ref": delivery_ref,
                "error": error,
                "operation": updated_operation.projection(),
            }
        )
        with self.database.transaction(write=True) as tx:
            current_import = tx.execute(
                "SELECT payload FROM r2s_imports WHERE import_id=?" + tx.lock_suffix(), (record.import_id,)
            ).fetchone()
            current_operation = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE import_id=?" + tx.lock_suffix(),
                (record.import_id,),
            ).fetchone()
            if current_import is None or current_operation is None:
                raise RuntimeStateConflictError("scene import hoặc operation đã bị xóa")
            stored_import = ImportedScene.model_validate_json(current_import[0])
            stored_operation = ImportOperationRecord.model_validate_json(current_operation[0])
            if stored_import.status != record.status or (
                stored_operation.operation_id != operation.operation_id
                or stored_operation.fencing_token != operation.fencing_token
                or stored_operation.status not in {"QUEUED", "RUNNING"}
            ):
                raise RuntimeStateConflictError("scene import operation đã đổi revision")
            tx.execute(
                "UPDATE r2s_imports SET payload=? WHERE import_id=?", (updated.model_dump_json(), record.import_id)
            )
            tx.execute(
                "UPDATE r2s_import_operations SET status=?, attempt=?, updated_at=?, owner_id=?, fencing_token=?, "
                "lease_expires_at=?, heartbeat_at=?, payload=? WHERE import_id=?",
                (
                    updated_operation.status,
                    updated_operation.attempt,
                    updated_operation.updated_at.isoformat(),
                    updated_operation.owner_id,
                    updated_operation.fencing_token,
                    None,
                    updated_operation.heartbeat_at.isoformat() if updated_operation.heartbeat_at else None,
                    updated_operation.model_dump_json(),
                    record.import_id,
                ),
            )
        return updated

    def recover_legacy_packaging(self) -> int:
        """Queue old PACKAGING records once; never enqueue READY or already-live operations."""
        recovered = 0
        with self.database.transaction(write=True) as tx:
            rows = tx.execute("SELECT import_id, payload FROM r2s_imports").fetchall()
            for import_id, payload in rows:
                record = ImportedScene.model_validate_json(payload)
                if record.status != "PACKAGING" or record.delivery_ref is not None:
                    continue
                exists = tx.execute("SELECT 1 FROM r2s_import_operations WHERE import_id=?", (import_id,)).fetchone()
                if exists is not None:
                    continue
                upload_row = tx.execute(
                    "SELECT payload FROM r2s_uploads WHERE upload_id=?", (record.upload_id,)
                ).fetchone()
                if upload_row is None:
                    failed = record.model_copy(
                        update={"status": "FAILED", "error": "Không còn file nguồn; hãy tải lại scene 3DGS."}
                    )
                    tx.execute(
                        "UPDATE r2s_imports SET payload=? WHERE import_id=?",
                        (failed.model_dump_json(), import_id),
                    )
                    continue
                upload = UploadRecord.model_validate_json(upload_row[0])
                operation = self._new_operation(record, upload, None)
                tx.execute(
                    "INSERT INTO r2s_import_operations "
                    "(operation_id, import_id, status, attempt, requester_id, request_fingerprint, created_at, "
                    "updated_at, fencing_token, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        operation.operation_id,
                        operation.import_id,
                        operation.status,
                        operation.attempt,
                        record.created_by or _ANONYMOUS_REQUESTER,
                        self._request_fingerprint(record.upload_id, record.name),
                        operation.created_at.isoformat(),
                        operation.updated_at.isoformat(),
                        operation.fencing_token,
                        operation.model_dump_json(),
                    ),
                )
                recovered += 1
        self._legacy_recovery_done = True
        return recovered

    def process_next(self, gpu_index: int | None, worker_id: str | None = None) -> bool:
        """Claim and process one durable import; called only by the standalone worker."""
        if not self._legacy_recovery_done:
            self.recover_legacy_packaging()
            self._legacy_recovery_done = True
        now = datetime.now(UTC)
        worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE status IN ('QUEUED','WAITING') "
                "ORDER BY created_at, operation_id LIMIT 1" + tx.lock_suffix()
            ).fetchone()
            if row is None:
                return False
            operation = ImportOperationRecord.model_validate_json(row[0])
            claimed = operation.model_copy(
                update={
                    "status": "RUNNING",
                    "attempt": operation.attempt + 1,
                    "owner_id": worker_id,
                    "fencing_token": operation.fencing_token + 1,
                    "lease_expires_at": now + timedelta(seconds=_IMPORT_LEASE_SECONDS),
                    "heartbeat_at": now,
                    "updated_at": now,
                }
            )
            cursor = tx.execute(
                "UPDATE r2s_import_operations SET status=?, attempt=?, updated_at=?, owner_id=?, fencing_token=?, "
                "lease_expires_at=?, heartbeat_at=?, payload=? WHERE operation_id=? AND status IN ('QUEUED','WAITING')",
                (
                    claimed.status,
                    claimed.attempt,
                    claimed.updated_at.isoformat(),
                    claimed.owner_id,
                    claimed.fencing_token,
                    claimed.lease_expires_at.isoformat() if claimed.lease_expires_at else None,
                    claimed.heartbeat_at.isoformat() if claimed.heartbeat_at else None,
                    claimed.model_dump_json(),
                    claimed.operation_id,
                ),
            )
            if cursor.rowcount != 1:
                return False
            import_row = tx.execute(
                "SELECT payload FROM r2s_imports WHERE import_id=?", (claimed.import_id,)
            ).fetchone()
            upload_row = tx.execute(
                "SELECT payload FROM r2s_uploads WHERE upload_id=?", (claimed.upload_id,)
            ).fetchone()
        if import_row is None:
            return True
        record = ImportedScene.model_validate_json(import_row[0])
        if record.status == "READY" and record.delivery_ref is not None:
            self._finish(record, claimed, status="READY", delivery_ref=record.delivery_ref)
            return True
        if record.status == "FAILED":
            self._finish(record, claimed, status="FAILED", error=record.error)
            return True
        if upload_row is None:
            self._finish(record, claimed, status="FAILED", error="Không còn file nguồn; hãy tải lại scene 3DGS.")
            return True
        upload = UploadRecord.model_validate_json(upload_row[0])
        if upload.checksum != claimed.upload_checksum or upload.upload_id != claimed.upload_id:
            self._finish(record, claimed, status="FAILED", error="Checksum file nguồn đã thay đổi; cần tải lại scene.")
            return True
        self.package(claimed.import_id, upload, claimed.gpu_index if claimed.gpu_index is not None else gpu_index)
        return True

    def package(self, import_id: str, upload: UploadRecord, gpu_index: int | None) -> ImportedScene:
        """Package PLY as SOG or preserve uploaded SOG bytes; publish before committing READY."""
        record = self.get(import_id)
        if record.status != "PACKAGING":
            return record
        operation = self._operation_record(import_id)
        workspace = self.workspace_root / import_id / uuid4().hex
        try:
            source = self.resolver.require_uri(upload.artifact_uri, upload.checksum)
            if record.input_kind == GaussianViewFormat.SOG:
                sog = source
            else:
                workspace.mkdir(parents=True, exist_ok=False)
                if record.input_kind == GaussianViewFormat.PLY_COLMAP:
                    member = upload.detection.ply_member if upload.detection else None
                    if member is None:
                        raise SceneImportError("Upload ZIP thiếu thông tin file PLY đã nhận diện")
                    source = extract_member(source, member, workspace / "input.ply")
                sog = package_splat(source, workspace / "sog", gpu_index)
            checksum = self._checksum_file(sog)
            digest = checksum.removeprefix("sha256:")
            uri = f"artifact://jobs/{import_id}/import/{digest}.sog"
            reference = ProductArtifactRef(
                artifact_type="VisualArtifact",
                schema_version="1.0",
                artifact_uri=uri,
                artifact_checksum=checksum,
                data_class=ArtifactDataClass.DERIVED,
                producer_stage=StageId.VISUAL_RECON,
                job_id=import_id,
                source_provenance={
                    "visual_source": "user_import",
                    "source_format": record.input_kind.value,
                    "upload_checksum": upload.checksum,
                },
            )
            publication = StreamingPublication(self.resolver, uri, max_bytes=max(1, sog.stat().st_size))
            try:
                with sog.open("rb") as source_stream:
                    while chunk := source_stream.read(1 << 20):
                        publication.write(chunk)
                if publication.commit() != checksum:
                    raise ValueError("Published SOG checksum changed while copying")
            except Exception:
                publication.abort()
                raise
        except RuntimeStateConflictError:
            raise
        except Exception as error:  # noqa: BLE001 - process boundary includes conversion and remote publication failures.
            logger.warning("Import %s packaging failed cause=%s", import_id, type(error).__name__)
            return self._finish(
                record,
                operation,
                status="FAILED",
                error="Không chuẩn bị được scene 3DGS; kiểm file nguồn và cấu hình worker rồi thử lại.",
            )
        return self._finish(record, operation, status="READY", delivery_ref=reference, error=None)

    def content_path(self, import_id: str) -> Path:
        """Đường dẫn cục bộ SOG đã kiểm checksum (kéo từ kho file nếu cần)."""
        record = self.get(import_id)
        if record.status != "READY" or record.delivery_ref is None:
            raise SceneImportError("Scene import chưa sẵn sàng")
        return self.resolver.require(record.delivery_ref)
