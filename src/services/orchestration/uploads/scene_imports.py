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
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.input_assembly import (
    GaussianViewFormat,
    GaussianViewImportIntent,
    verify_gaussian_view_intent_checksum,
)
from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import ArtifactResolver, StreamingPublication
from src.services.orchestration.artifacts.errors import (
    ArtifactAlreadyExistsError,
    ArtifactChecksumError,
    ArtifactNotFoundError,
    ArtifactStoreError,
)
from src.services.orchestration.auth.models import DisplayName, Role
from src.services.orchestration.jobs.admission import (
    OperationAdmissionRequest,
    OperationAdmissionResult,
    ResourceAdmission,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads.models import UploadRecord
from src.services.reconstruction import extract_member, package_splat, validate_sog_runtime
from src.services.reconstruction.adapters.voxel_runtime import GeometryCancelledError, GeometryError
from src.services.reconstruction.inputs.detect import (
    InputRejectedError,
    detect_input,
    validate_sog_bundle,
)

logger = logging.getLogger(__name__)

ImportStatus = Literal["PACKAGING", "READY", "FAILED", "CANCELLED"]
ImportOperationStatus = Literal["QUEUED", "WAITING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
ImportAttemptStatus = Literal["RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"]
_ANONYMOUS_REQUESTER = "__anonymous__"
_IMPORT_LEASE_SECONDS = 300
_IMPORT_HEARTBEAT_SECONDS = 20.0
_IMPORT_CANCEL_POLL_SECONDS = 0.5
ImportFailureCode = Literal[
    "invalid_source",
    "source_unavailable",
    "runtime_failure",
    "publication_failure",
    "packaging_failure",
    "resource_conflict",
    "resource_wait",
    "worker_interrupted",
]


class ImportAttemptRecord(BaseModel):
    attempt: int = Field(ge=1)
    status: ImportAttemptStatus
    started_at: datetime
    finished_at: datetime | None = None
    failure_code: ImportFailureCode | None = None
    retryable: bool | None = None
    error: str | None = None


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
    attempt_history: list[ImportAttemptRecord] = Field(default_factory=list)
    owner_id: str | None = None
    lease_token: str | None = None
    fencing_token: int = Field(ge=0)
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    delivery_ref: ProductArtifactRef | None = None
    error: str | None = None
    failure_code: ImportFailureCode | None = None
    retryable: bool | None = None
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None

    def projection(self) -> ImportOperationProjection:
        return ImportOperationProjection(
            operation_id=self.operation_id,
            status=self.status,
            attempt=self.attempt,
            attempt_history=self.attempt_history,
            error=self.error,
            failure_code=self.failure_code,
            retryable=self.retryable,
            cancel_requested=self.cancel_requested,
            cancel_requested_at=self.cancel_requested_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ImportOperationProjection(BaseModel):
    """Safe public subset of the durable operation record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    status: ImportOperationStatus
    attempt: int = Field(ge=0)
    attempt_history: list[ImportAttemptRecord] = Field(default_factory=list)
    error: str | None = None
    failure_code: ImportFailureCode | None = None
    retryable: bool | None = None
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None
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
    #: Exact unified-upload selection; omitted for imports created through the legacy separate form.
    input_intent: GaussianViewImportIntent | None = Field(default=None, exclude_if=lambda value: value is None)


class SceneImportError(ValueError):
    """Đầu vào/trạng thái import không hợp lệ; message hiển thị được."""


class ImportNotFoundError(LookupError):
    """Không có import với ID này."""


class ImportService:
    """Mỗi request một instance; state nằm ở DB + artifact store."""

    def __init__(
        self,
        database: RuntimeDatabase,
        resolver: ArtifactResolver,
        workspace_root: Path,
        *,
        max_uncompressed_bytes: int | None = None,
    ) -> None:
        self.database = database
        self.resolver = resolver
        self.workspace_root = workspace_root
        self.max_uncompressed_bytes = max_uncompressed_bytes
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
    def _request_fingerprint(upload_id: str, name: str, input_intent: GaussianViewImportIntent | None = None) -> str:
        payload: dict[str, object] = {"upload_id": upload_id, "name": name}
        if input_intent is not None:
            payload["input_intent"] = input_intent.model_dump(
                mode="json",
                exclude={"intent_id", "selected_at", "intent_checksum"},
            )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
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
        input_intent: GaussianViewImportIntent | None = None,
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
        if input_intent is not None:
            verify_gaussian_view_intent_checksum(input_intent)
            if input_intent.source_checksum != upload.checksum or input_intent.source_format != input_kind:
                raise SceneImportError("Gaussian view intent khác source upload đã nhận diện")
        if idempotency_key is not None and (not idempotency_key.strip() or len(idempotency_key) > 128):
            raise SceneImportError("Idempotency-Key phải dài 1..128 ký tự")
        normalized_name = name.strip() or upload.original_name
        fingerprint = self._request_fingerprint(upload.upload_id, normalized_name, input_intent)
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
            input_intent=input_intent,
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

    def retry(self, import_id: str) -> ImportedScene:
        """Atomically queue one new attempt only for known transient failures."""
        now = datetime.now(UTC)
        retryable_codes = {"runtime_failure", "publication_failure", "source_unavailable", "worker_interrupted"}
        with self.database.transaction(write=True) as tx:
            import_row = tx.execute(
                "SELECT payload FROM r2s_imports WHERE import_id=?" + tx.lock_suffix(), (import_id,)
            ).fetchone()
            operation_row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE import_id=?" + tx.lock_suffix(), (import_id,)
            ).fetchone()
            if import_row is None or operation_row is None:
                raise ImportNotFoundError(f"không tìm thấy scene import: {import_id}")
            record = ImportedScene.model_validate_json(import_row[0])
            operation = ImportOperationRecord.model_validate_json(operation_row[0])
            if operation.status in {"QUEUED", "WAITING", "RUNNING"}:
                return record.model_copy(update={"operation": operation.projection()})
            if (
                operation.status != "FAILED"
                or operation.retryable is not True
                or operation.failure_code not in retryable_codes
            ):
                raise SceneImportError("Lỗi hiện tại không cho phép thử lại; scene và chẩn đoán được giữ nguyên.")
            queued = operation.model_copy(
                update={
                    "status": "QUEUED",
                    "owner_id": None,
                    "lease_token": None,
                    "fencing_token": operation.fencing_token + 1,
                    "lease_expires_at": None,
                    "heartbeat_at": None,
                    "updated_at": now,
                    "delivery_ref": None,
                    "error": None,
                    "failure_code": None,
                    "retryable": None,
                    "cancel_requested": False,
                    "cancel_requested_at": None,
                }
            )
            queued_record = record.model_copy(
                update={
                    "status": "PACKAGING",
                    "delivery_ref": None,
                    "error": None,
                    "operation": queued.projection(),
                }
            )
            tx.execute(
                "UPDATE r2s_imports SET payload=? WHERE import_id=?", (queued_record.model_dump_json(), import_id)
            )
            tx.execute(
                "UPDATE r2s_import_operations SET status=?, attempt=?, updated_at=?, owner_id=NULL, fencing_token=?, "
                "lease_expires_at=NULL, heartbeat_at=NULL, payload=? WHERE import_id=?",
                (
                    queued.status,
                    queued.attempt,
                    queued.updated_at.isoformat(),
                    queued.fencing_token,
                    queued.model_dump_json(),
                    import_id,
                ),
            )
        return self.get(import_id)

    def cancel(self, import_id: str) -> ImportedScene:
        """Persist cancellation; a live worker acknowledges only after its child exits."""
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            import_row = tx.execute(
                "SELECT payload FROM r2s_imports WHERE import_id=?" + tx.lock_suffix(), (import_id,)
            ).fetchone()
            operation_row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE import_id=?" + tx.lock_suffix(), (import_id,)
            ).fetchone()
            if import_row is None or operation_row is None:
                raise ImportNotFoundError(f"không tìm thấy scene import: {import_id}")
            record = ImportedScene.model_validate_json(import_row[0])
            operation = ImportOperationRecord.model_validate_json(operation_row[0])
            if operation.status == "CANCELLED":
                return record.model_copy(update={"operation": operation.projection()})
            if operation.status not in {"QUEUED", "WAITING", "RUNNING"}:
                raise SceneImportError("Không thể hủy scene import đã kết thúc.")
            if operation.status == "RUNNING":
                if not operation.cancel_requested:
                    requested = operation.model_copy(
                        update={
                            "cancel_requested": True,
                            "cancel_requested_at": now,
                            "error": "Đang dừng worker an toàn trước khi xác nhận hủy…",
                            "updated_at": now,
                        }
                    )
                    tx.execute(
                        "UPDATE r2s_import_operations SET updated_at=?, payload=? WHERE import_id=?",
                        (now.isoformat(), requested.model_dump_json(), import_id),
                    )
                else:
                    requested = operation
                return record.model_copy(update={"operation": requested.projection()})

            error = "Đã hủy theo yêu cầu."
            cancelled = operation.model_copy(
                update={
                    "status": "CANCELLED",
                    "owner_id": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "heartbeat_at": now,
                    "updated_at": now,
                    "error": error,
                    "failure_code": None,
                    "retryable": False,
                    "cancel_requested": True,
                    "cancel_requested_at": now,
                }
            )
            cancelled_record = record.model_copy(
                update={
                    "status": "CANCELLED",
                    "delivery_ref": None,
                    "error": error,
                    "operation": cancelled.projection(),
                }
            )
            tx.execute(
                "UPDATE r2s_imports SET payload=? WHERE import_id=?", (cancelled_record.model_dump_json(), import_id)
            )
            tx.execute(
                "UPDATE r2s_import_operations SET status=?, updated_at=?, owner_id=NULL, lease_expires_at=NULL, "
                "heartbeat_at=?, payload=? WHERE import_id=?",
                (
                    cancelled.status,
                    now.isoformat(),
                    now.isoformat(),
                    cancelled.model_dump_json(),
                    import_id,
                ),
            )
        return self.get(import_id)

    def _finish(
        self,
        record: ImportedScene,
        operation: ImportOperationRecord,
        *,
        status: Literal["READY", "FAILED", "CANCELLED"],
        delivery_ref: ProductArtifactRef | None = None,
        error: str | None = None,
        failure_code: ImportFailureCode | None = None,
        retryable: bool | None = None,
    ) -> ImportedScene:
        now = datetime.now(UTC)
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
                or stored_operation.owner_id != operation.owner_id
                or stored_operation.lease_token != operation.lease_token
                or stored_operation.attempt != operation.attempt
                or stored_operation.status != "RUNNING"
                or stored_operation.lease_expires_at is None
                or stored_operation.lease_expires_at <= now
            ):
                raise RuntimeStateConflictError("scene import operation đã đổi revision")
            if stored_operation.cancel_requested:
                status = "CANCELLED"
                delivery_ref = None
                error = "Đã hủy theo yêu cầu."
                failure_code = None
                retryable = False
            operation_status: ImportOperationStatus = {
                "READY": "SUCCEEDED",
                "FAILED": "FAILED",
                "CANCELLED": "CANCELLED",
            }[status]
            history = list(stored_operation.attempt_history)
            for index in range(len(history) - 1, -1, -1):
                previous = history[index]
                if previous.attempt == stored_operation.attempt:
                    if previous.status == "RUNNING":
                        history[index] = previous.model_copy(
                            update={
                                "status": operation_status,
                                "finished_at": now,
                                "failure_code": failure_code,
                                "retryable": retryable,
                                "error": error,
                            }
                        )
                    break
            updated_operation = stored_operation.model_copy(
                update={
                    "status": operation_status,
                    "attempt_history": history,
                    "owner_id": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "heartbeat_at": now,
                    "updated_at": now,
                    "delivery_ref": delivery_ref,
                    "error": error,
                    "failure_code": failure_code,
                    "retryable": retryable,
                }
            )
            updated = stored_import.model_copy(
                update={
                    "status": status,
                    "delivery_ref": delivery_ref,
                    "error": error,
                    "operation": updated_operation.projection(),
                }
            )
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

    @staticmethod
    def _lease_matches(stored: ImportOperationRecord, claimed: ImportOperationRecord, now: datetime) -> bool:
        return (
            stored.operation_id == claimed.operation_id
            and stored.fencing_token == claimed.fencing_token
            and stored.owner_id == claimed.owner_id
            and stored.lease_token == claimed.lease_token
            and stored.status == "RUNNING"
            and stored.lease_expires_at is not None
            and stored.lease_expires_at > now
        )

    def _touch_lease(self, claimed: ImportOperationRecord) -> bool:
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE operation_id=?" + tx.lock_suffix(),
                (claimed.operation_id,),
            ).fetchone()
            if row is None:
                return False
            stored = ImportOperationRecord.model_validate_json(row[0])
            if not self._lease_matches(stored, claimed, now):
                return False
            touched = stored.model_copy(
                update={
                    "heartbeat_at": now,
                    "lease_expires_at": now + timedelta(seconds=_IMPORT_LEASE_SECONDS),
                    "updated_at": now,
                }
            )
            tx.execute(
                "UPDATE r2s_import_operations SET updated_at=?, lease_expires_at=?, heartbeat_at=?, payload=? "
                "WHERE operation_id=?",
                (
                    touched.updated_at.isoformat(),
                    touched.lease_expires_at.isoformat() if touched.lease_expires_at else None,
                    touched.heartbeat_at.isoformat() if touched.heartbeat_at else None,
                    touched.model_dump_json(),
                    claimed.operation_id,
                ),
            )
        return True

    def _cancellation_state(self, claimed: ImportOperationRecord) -> tuple[bool, bool]:
        """Return (cancel requested, lease lost) for this exact worker fence."""
        now = datetime.now(UTC)
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE operation_id=?", (claimed.operation_id,)
            ).fetchone()
        if row is None:
            return False, True
        stored = ImportOperationRecord.model_validate_json(row[0])
        if not self._lease_matches(stored, claimed, now):
            return False, True
        return stored.cancel_requested, False

    def _fail_orphan(self, claimed: ImportOperationRecord) -> bool:
        """Terminate a corrupt operation whose parent import row disappeared."""
        now = datetime.now(UTC)
        failed = claimed.model_copy(
            update={
                "status": "FAILED",
                "owner_id": None,
                "lease_token": None,
                "lease_expires_at": None,
                "heartbeat_at": now,
                "updated_at": now,
                "error": "Scene import record is missing.",
                "failure_code": "invalid_source",
                "retryable": False,
            }
        )
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE operation_id=?" + tx.lock_suffix(),
                (claimed.operation_id,),
            ).fetchone()
            if row is None or not self._lease_matches(ImportOperationRecord.model_validate_json(row[0]), claimed, now):
                return False
            tx.execute(
                "UPDATE r2s_import_operations SET status=?, updated_at=?, owner_id=NULL, lease_expires_at=NULL, "
                "heartbeat_at=?, payload=? WHERE operation_id=?",
                (
                    failed.status,
                    failed.updated_at.isoformat(),
                    failed.heartbeat_at.isoformat() if failed.heartbeat_at else None,
                    failed.model_dump_json(),
                    claimed.operation_id,
                ),
            )
        return True

    def _start_heartbeat(
        self,
        claimed: ImportOperationRecord,
        admission: ResourceAdmission,
        request_box: list[OperationAdmissionRequest | None],
        lease_lost: Event,
        cancel_requested: Event,
    ) -> tuple[Event, Thread]:
        stop = Event()

        def beat() -> None:
            last_touch = time.monotonic()
            while not stop.wait(_IMPORT_CANCEL_POLL_SECONDS):
                requested, lease_is_lost = self._cancellation_state(claimed)
                if lease_is_lost:
                    lease_lost.set()
                    cancel_requested.set()
                    logger.warning(
                        "Import lease mất quyền import=%s fencing=%s", claimed.import_id, claimed.fencing_token
                    )
                    return
                if requested:
                    cancel_requested.set()
                    return
                if time.monotonic() - last_touch < _IMPORT_HEARTBEAT_SECONDS:
                    continue
                if not self._touch_lease(claimed):
                    lease_lost.set()
                    cancel_requested.set()
                    logger.warning(
                        "Import lease mất quyền import=%s fencing=%s", claimed.import_id, claimed.fencing_token
                    )
                    return
                last_touch = time.monotonic()
                request = request_box[0]
                if request is not None and not admission.touch_operation(request):
                    lease_lost.set()
                    cancel_requested.set()
                    logger.warning(
                        "Import reservation mất quyền import=%s fencing=%s",
                        claimed.import_id,
                        claimed.fencing_token,
                    )
                    return

        thread = Thread(target=beat, name=f"import-lease-{claimed.import_id[-8:]}", daemon=True)
        thread.start()
        return stop, thread

    def _wait_for_resources(self, claimed: ImportOperationRecord, result: OperationAdmissionResult) -> bool:
        now = datetime.now(UTC)
        details = [f"{resource} ({result.reasons.get(resource, 'unmeasured')})" for resource in result.waiting_on]
        error = (
            "Worker đang chờ tài nguyên: " + ", ".join(details) + "."
            if details
            else "Worker đang chờ để nhận scene 3DGS."
        )
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE operation_id=?" + tx.lock_suffix(),
                (claimed.operation_id,),
            ).fetchone()
            if row is None:
                return False
            stored = ImportOperationRecord.model_validate_json(row[0])
            if not self._lease_matches(stored, claimed, now):
                return False
            if stored.cancel_requested:
                cancelled = stored.model_copy(
                    update={
                        "status": "CANCELLED",
                        "owner_id": None,
                        "lease_token": None,
                        "lease_expires_at": None,
                        "heartbeat_at": now,
                        "updated_at": now,
                        "error": "Đã hủy theo yêu cầu.",
                        "failure_code": None,
                        "retryable": False,
                    }
                )
                import_row = tx.execute(
                    "SELECT payload FROM r2s_imports WHERE import_id=?" + tx.lock_suffix(),
                    (claimed.import_id,),
                ).fetchone()
                if import_row is not None:
                    record = ImportedScene.model_validate_json(import_row[0])
                    cancelled_record = record.model_copy(
                        update={
                            "status": "CANCELLED",
                            "delivery_ref": None,
                            "error": cancelled.error,
                            "operation": cancelled.projection(),
                        }
                    )
                    tx.execute(
                        "UPDATE r2s_imports SET payload=? WHERE import_id=?",
                        (cancelled_record.model_dump_json(), claimed.import_id),
                    )
                tx.execute(
                    "UPDATE r2s_import_operations SET status=?, updated_at=?, owner_id=NULL, "
                    "lease_expires_at=NULL, heartbeat_at=?, payload=? WHERE operation_id=?",
                    (
                        cancelled.status,
                        cancelled.updated_at.isoformat(),
                        cancelled.heartbeat_at.isoformat() if cancelled.heartbeat_at else None,
                        cancelled.model_dump_json(),
                        claimed.operation_id,
                    ),
                )
                return True
            waiting = stored.model_copy(
                update={
                    "status": "WAITING",
                    "owner_id": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "heartbeat_at": now,
                    "updated_at": now,
                    "error": error,
                    "failure_code": "resource_wait",
                    "retryable": None,
                }
            )
            tx.execute(
                "UPDATE r2s_import_operations SET status=?, updated_at=?, owner_id=NULL, lease_expires_at=NULL, "
                "heartbeat_at=?, payload=? WHERE operation_id=?",
                (
                    waiting.status,
                    waiting.updated_at.isoformat(),
                    waiting.heartbeat_at.isoformat() if waiting.heartbeat_at else None,
                    waiting.model_dump_json(),
                    claimed.operation_id,
                ),
            )
        return True

    def _start_attempt(self, claimed: ImportOperationRecord) -> ImportOperationRecord | None:
        now = datetime.now(UTC)
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE operation_id=?" + tx.lock_suffix(),
                (claimed.operation_id,),
            ).fetchone()
            if row is None:
                return None
            stored = ImportOperationRecord.model_validate_json(row[0])
            if not self._lease_matches(stored, claimed, now) or stored.cancel_requested:
                return None
            attempt = stored.attempt + 1
            history = [
                *stored.attempt_history,
                ImportAttemptRecord(attempt=attempt, status="RUNNING", started_at=now),
            ]
            started = stored.model_copy(
                update={
                    "attempt": attempt,
                    "attempt_history": history,
                    "updated_at": now,
                    "error": None,
                    "failure_code": None,
                    "retryable": None,
                }
            )
            tx.execute(
                "UPDATE r2s_import_operations SET attempt=?, updated_at=?, payload=? WHERE operation_id=?",
                (started.attempt, started.updated_at.isoformat(), started.model_dump_json(), claimed.operation_id),
            )
        return started

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

    def process_next(self, *, admission: ResourceAdmission, worker_id: str | None = None) -> bool:
        """Claim one durable import, reserve its resources, then package and commit."""
        if not self._legacy_recovery_done:
            self.recover_legacy_packaging()
            self._legacy_recovery_done = True
        now = datetime.now(UTC)
        worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_import_operations WHERE status IN ('QUEUED','WAITING') "
                "OR (status='RUNNING' AND (lease_expires_at IS NULL OR lease_expires_at<=?)) "
                "ORDER BY created_at, operation_id LIMIT 1" + tx.lock_suffix(),
                (now.isoformat(),),
            ).fetchone()
            if row is None:
                return False
            operation = ImportOperationRecord.model_validate_json(row[0])
            attempt_history = list(operation.attempt_history)
            if operation.status == "RUNNING":
                for index in range(len(attempt_history) - 1, -1, -1):
                    previous = attempt_history[index]
                    if previous.attempt == operation.attempt and previous.status == "RUNNING":
                        attempt_history[index] = previous.model_copy(
                            update={
                                "status": "INTERRUPTED",
                                "finished_at": now,
                                "failure_code": "worker_interrupted",
                                "retryable": True,
                                "error": "Worker lease expired before the attempt completed.",
                            }
                        )
                        break
            claimed = operation.model_copy(
                update={
                    "status": "RUNNING",
                    "attempt_history": attempt_history,
                    "owner_id": worker_id,
                    "lease_token": uuid4().hex,
                    "fencing_token": operation.fencing_token + 1,
                    "lease_expires_at": now + timedelta(seconds=_IMPORT_LEASE_SECONDS),
                    "heartbeat_at": now,
                    "updated_at": now,
                    "error": None,
                    "failure_code": None,
                    "retryable": None,
                }
            )
            cursor = tx.execute(
                "UPDATE r2s_import_operations SET status=?, updated_at=?, owner_id=?, fencing_token=?, "
                "lease_expires_at=?, heartbeat_at=?, payload=? WHERE operation_id=? AND "
                "(status IN ('QUEUED','WAITING') OR (status='RUNNING' AND "
                "(lease_expires_at IS NULL OR lease_expires_at<=?)))",
                (
                    claimed.status,
                    claimed.updated_at.isoformat(),
                    claimed.owner_id,
                    claimed.fencing_token,
                    claimed.lease_expires_at.isoformat() if claimed.lease_expires_at else None,
                    claimed.heartbeat_at.isoformat() if claimed.heartbeat_at else None,
                    claimed.model_dump_json(),
                    claimed.operation_id,
                    now.isoformat(),
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

        request_box: list[OperationAdmissionRequest | None] = [None]
        lease_lost = Event()
        cancel_requested = Event()
        heartbeat_stop, heartbeat_thread = self._start_heartbeat(
            claimed, admission, request_box, lease_lost, cancel_requested
        )
        reserved = False
        request: OperationAdmissionRequest | None = None
        finish_operation = claimed
        try:
            if import_row is None:
                self._fail_orphan(claimed)
                return True
            record = ImportedScene.model_validate_json(import_row[0])
            if record.status == "READY" and record.delivery_ref is not None:
                self.resolver.require(record.delivery_ref)
                return self._finish(record, claimed, status="READY", delivery_ref=record.delivery_ref).status == "READY"
            if record.status == "FAILED":
                self._finish(
                    record,
                    claimed,
                    status="FAILED",
                    error=record.error,
                    failure_code="packaging_failure",
                    retryable=False,
                )
                return True
            if claimed.cancel_requested:
                cancel_requested.set()
                self._finish(
                    record,
                    claimed,
                    status="CANCELLED",
                    error="Đã hủy theo yêu cầu.",
                    retryable=False,
                )
                return True
            if upload_row is None:
                self._finish(
                    record,
                    claimed,
                    status="FAILED",
                    error="Không còn file nguồn; hãy tải lại scene 3DGS.",
                    failure_code="source_unavailable",
                    retryable=False,
                )
                return True
            upload = UploadRecord.model_validate_json(upload_row[0])
            if upload.checksum != claimed.upload_checksum or upload.upload_id != claimed.upload_id:
                self._finish(
                    record,
                    claimed,
                    status="FAILED",
                    error="Checksum file nguồn đã thay đổi; cần tải lại scene.",
                    failure_code="invalid_source",
                    retryable=False,
                )
                return True
            if record.input_kind != upload.input_kind or claimed.packaging_config_checksum != self._config_checksum(
                record.input_kind, claimed.gpu_index
            ):
                self._finish(
                    record,
                    claimed,
                    status="FAILED",
                    error="Cấu hình hoặc loại file import đã thay đổi; cần tạo yêu cầu mới.",
                    failure_code="invalid_source",
                    retryable=False,
                )
                return True
            source = self.resolver.require_uri(upload.artifact_uri, upload.checksum)
            detection = detect_input(source, self._uncompressed_limit(upload))
            if detection.kind != record.input_kind.value:
                self._finish(
                    record,
                    claimed,
                    status="FAILED",
                    error="Nội dung file nguồn không khớp với loại đã nhận diện; hãy tải lại scene.",
                    failure_code="invalid_source",
                    retryable=False,
                )
                return True
            evidence = detection.gaussian or detection.sog
            if evidence is None:
                raise InputRejectedError("source has no validated Gaussian count")
            gaussian_count = evidence.gaussian_count
            gpu_required = record.input_kind != GaussianViewFormat.SOG and claimed.gpu_index is not None
            profile = admission.operation_profile_for_import(
                gaussian_count=gaussian_count,
                source_size_bytes=upload.size_bytes,
                gpu_required=gpu_required,
            )
            request = OperationAdmissionRequest(
                operation_kind="import_package",
                operation_id=claimed.operation_id,
                parent_kind="import",
                parent_id=claimed.import_id,
                input_checksum=claimed.upload_checksum,
                config_checksum=claimed.packaging_config_checksum,
                resources=profile,
                lease_token=claimed.lease_token,
                lease_generation=claimed.fencing_token,
            )
            result = admission.admit_operation(request)
            if result.status != "admitted":
                if result.status == "identity_conflict":
                    self._finish(
                        record,
                        claimed,
                        status="FAILED",
                        error="Operation admission phát hiện input/config không nhất quán.",
                        failure_code="resource_conflict",
                        retryable=False,
                    )
                    return True
                self._wait_for_resources(claimed, result)
                return False
            if cancel_requested.is_set():
                self._finish(
                    record,
                    claimed,
                    status="CANCELLED",
                    error="Đã hủy theo yêu cầu.",
                    retryable=False,
                )
                return True
            request_box[0] = request
            reserved = True
            running = self._start_attempt(claimed)
            if running is None:
                requested, _lease_is_lost = self._cancellation_state(claimed)
                if requested:
                    cancel_requested.set()
                    self._finish(
                        record,
                        claimed,
                        status="CANCELLED",
                        error="Đã hủy theo yêu cầu.",
                        retryable=False,
                    )
                return True
            finish_operation = running
            self.package(
                claimed.import_id,
                upload,
                claimed.gpu_index,
                operation=running,
                lease_lost=lease_lost,
                cancel_requested=cancel_requested,
            )
            return True
        except (ArtifactNotFoundError, ArtifactChecksumError) as error:
            if import_row is None:
                self._fail_orphan(claimed)
                return True
            logger.warning(
                "Import source validation failed import=%s cause=%s", claimed.import_id, type(error).__name__
            )
            record = ImportedScene.model_validate_json(import_row[0])
            self._finish(
                record,
                finish_operation,
                status="FAILED",
                error="File nguồn không còn khớp bản đã tải; hãy tải lại scene 3DGS.",
                failure_code="invalid_source",
                retryable=False,
            )
            return True
        except InputRejectedError as error:
            if import_row is None:
                self._fail_orphan(claimed)
                return True
            logger.info("Import source rejected import=%s cause=%s", claimed.import_id, type(error).__name__)
            record = ImportedScene.model_validate_json(import_row[0])
            self._finish(
                record,
                finish_operation,
                status="FAILED",
                error="File nguồn bị hỏng hoặc vượt giới hạn; hãy kiểm tra file rồi tải lại.",
                failure_code="invalid_source",
                retryable=False,
            )
            return True
        except RuntimeStateConflictError:
            logger.info(
                "Import result fenced after lease change import=%s fencing=%s",
                claimed.import_id,
                claimed.fencing_token,
            )
            return True
        except Exception as error:  # noqa: BLE001 - operation boundary stores only safe typed diagnostics.
            if import_row is None:
                logger.warning("Import worker failed import=%s cause=%s", claimed.import_id, type(error).__name__)
                self._fail_orphan(claimed)
                return True
            logger.warning("Import worker failed import=%s cause=%s", claimed.import_id, type(error).__name__)
            record = ImportedScene.model_validate_json(import_row[0])
            self._finish(
                record,
                finish_operation,
                status="FAILED",
                error="Không chuẩn bị được scene 3DGS; kiểm tra worker rồi thử lại.",
                failure_code="source_unavailable" if isinstance(error, ArtifactStoreError) else "packaging_failure",
                retryable=isinstance(error, ArtifactStoreError),
            )
            return True
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=_IMPORT_HEARTBEAT_SECONDS + 1)
            if reserved and request is not None:
                admission.release_operation(request)

    def _uncompressed_limit(self, upload: UploadRecord) -> int:
        return self.max_uncompressed_bytes or max(upload.size_bytes * 2, 1)

    def package(
        self,
        import_id: str,
        upload: UploadRecord,
        gpu_index: int | None,
        *,
        operation: ImportOperationRecord,
        lease_lost: Event,
        cancel_requested: Event,
    ) -> ImportedScene:
        """Package verified PLY/SOG to SOG and commit READY under the current lease."""
        record = self.get(import_id)
        if record.status != "PACKAGING":
            return record
        workspace = self.workspace_root / import_id / uuid4().hex
        try:
            if cancel_requested.is_set():
                raise GeometryCancelledError("Scene import was cancelled before packaging started")
            source = self.resolver.require_uri(upload.artifact_uri, upload.checksum)
            workspace.mkdir(parents=True, exist_ok=False)
            max_uncompressed_bytes = self._uncompressed_limit(upload)
            source_detection = detect_input(source, max_uncompressed_bytes)
            if source_detection.kind != record.input_kind.value:
                raise InputRejectedError("source kind changed after admission")
            if record.input_kind == GaussianViewFormat.SOG:
                sog = workspace / "source.sog"
                with source.open("rb") as source_stream, sog.open("xb") as target:
                    while chunk := source_stream.read(1 << 20):
                        if cancel_requested.is_set():
                            raise GeometryCancelledError("Scene import was cancelled while staging SOG")
                        target.write(chunk)
                if self._checksum_file(sog) != upload.checksum:
                    raise InputRejectedError("source SOG checksum changed while staging")
                sog_detection = validate_sog_bundle(sog, max_uncompressed_bytes)
                assert sog_detection.sog is not None
                expected_count = sog_detection.sog.gaussian_count
                expected_sh_bands = sog_detection.sog.sh_degree
            else:
                if record.input_kind == GaussianViewFormat.PLY_COLMAP:
                    member = source_detection.ply_member
                    if member is None:
                        raise InputRejectedError("ZIP source does not have one validated Gaussian PLY member")
                    source_ply = extract_member(
                        source,
                        member,
                        workspace / "input.ply",
                        max_uncompressed_bytes=max_uncompressed_bytes,
                        cancel_event=cancel_requested,
                    )
                    if self._checksum_file(source) != upload.checksum:
                        raise InputRejectedError("source ZIP checksum changed while extracting")
                else:
                    source_ply = workspace / "input.ply"
                    with source.open("rb") as source_stream, source_ply.open("xb") as target:
                        while chunk := source_stream.read(1 << 20):
                            if cancel_requested.is_set():
                                raise GeometryCancelledError("Scene import was cancelled while staging PLY")
                            target.write(chunk)
                if source_detection.gaussian is None:
                    raise InputRejectedError("PLY source lacks validated Gaussian inventory")
                if record.input_kind == GaussianViewFormat.PLY and self._checksum_file(source_ply) != upload.checksum:
                    raise InputRejectedError("source PLY checksum changed while staging")
                expected_count = source_detection.gaussian.gaussian_count
                expected_sh_bands = source_detection.gaussian.sh_degree
                sog = package_splat(source_ply, workspace / "sog", gpu_index, cancel_event=cancel_requested)
                sog_detection = validate_sog_bundle(sog, max_uncompressed_bytes)
                if (
                    sog_detection.sog is None
                    or sog_detection.sog.gaussian_count != expected_count
                    or sog_detection.sog.sh_degree != expected_sh_bands
                ):
                    raise InputRejectedError("Packaged SOG inventory differs from the PLY source")
            if cancel_requested.is_set():
                raise GeometryCancelledError("Scene import was cancelled before SOG validation")
            validate_sog_runtime(
                sog,
                workspace / "runtime-validation",
                expected_count=expected_count,
                expected_sh_bands=expected_sh_bands,
                cancel_event=cancel_requested,
            )
            if lease_lost.is_set():
                raise RuntimeStateConflictError("scene import lease or resource reservation expired")
            if cancel_requested.is_set():
                raise GeometryCancelledError("Scene import was cancelled before publication")
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
            self._publish_or_reuse(sog, uri, checksum, max_uncompressed_bytes, cancel_requested)
        except RuntimeStateConflictError:
            raise
        except GeometryCancelledError:
            return self._finish(
                record,
                operation,
                status="CANCELLED",
                error="Đã hủy theo yêu cầu.",
                retryable=False,
            )
        except GeometryError as error:
            logger.warning("Import %s runtime failed cause=%s", import_id, type(error).__name__)
            return self._finish(
                record,
                operation,
                status="FAILED",
                error="Worker không thể đọc hoặc nén scene 3DGS; kiểm tra runtime rồi thử lại.",
                failure_code="runtime_failure",
                retryable=True,
            )
        except (InputRejectedError, ValueError) as error:
            logger.warning("Import %s input/package validation failed cause=%s", import_id, type(error).__name__)
            return self._finish(
                record,
                operation,
                status="FAILED",
                error="File nguồn hoặc SOG kết quả không hợp lệ; hãy kiểm tra file và thử lại.",
                failure_code="invalid_source" if isinstance(error, InputRejectedError) else "packaging_failure",
                retryable=False,
            )
        except ArtifactStoreError as error:
            logger.warning("Import %s publication failed cause=%s", import_id, type(error).__name__)
            return self._finish(
                record,
                operation,
                status="FAILED",
                error="Chưa lưu được bản xem scene; có thể thử lại sau.",
                failure_code="publication_failure",
                retryable=True,
            )
        except Exception as error:  # noqa: BLE001 - external runtime and publication boundaries are typed below.
            logger.warning("Import %s packaging failed cause=%s", import_id, type(error).__name__)
            return self._finish(
                record,
                operation,
                status="FAILED",
                error="Không chuẩn bị được scene 3DGS; kiểm tra worker rồi thử lại.",
                failure_code="runtime_failure",
                retryable=True,
            )
        if lease_lost.is_set():
            raise RuntimeStateConflictError("scene import lease or resource reservation expired before READY")
        return self._finish(record, operation, status="READY", delivery_ref=reference, error=None)

    def _publish_or_reuse(
        self,
        sog: Path,
        uri: str,
        checksum: str,
        max_bytes: int,
        cancel_requested: Event | None = None,
    ) -> None:
        existing = self.resolver.locate(uri, fresh=True)
        if existing is not None:
            if self._checksum_file(existing) != checksum:
                raise ArtifactChecksumError("existing immutable SOG artifact has a different checksum")
            self.resolver.require_uri(uri, checksum)
            self.resolver.published(uri)
            return
        try:
            publication = StreamingPublication(self.resolver, uri, max_bytes=max(1, max_bytes))
        except ArtifactAlreadyExistsError:
            self.resolver.require_uri(uri, checksum)
            return
        try:
            with sog.open("rb") as source_stream:
                while chunk := source_stream.read(1 << 20):
                    if cancel_requested is not None and cancel_requested.is_set():
                        raise GeometryCancelledError("Scene import was cancelled during publication")
                    publication.write(chunk)
            if publication.commit() != checksum:
                raise ArtifactChecksumError("published SOG checksum changed while copying")
        except ArtifactAlreadyExistsError:
            publication.abort()
            self.resolver.require_uri(uri, checksum)
        except Exception:
            publication.abort()
            raise

    def content_path(self, import_id: str) -> Path:
        """Đường dẫn cục bộ SOG đã kiểm checksum (kéo từ kho file nếu cần)."""
        record = self.get(import_id)
        if record.status != "READY" or record.delivery_ref is None:
            raise SceneImportError("Scene import chưa sẵn sàng")
        return self.resolver.require(record.delivery_ref)
