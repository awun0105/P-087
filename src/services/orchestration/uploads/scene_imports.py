"""Scene 3DGS người dùng tải lên — chỉ xem/chỉnh sửa (ADR 0004 §3, gói 5), ranh giới EX-PRODUCT.

Không phải job: không qua REC-06/05 và không tạo ReconstructionPreview (contract yêu cầu
camera + Brush). Bản ghi nằm ở `r2s_imports`; bytes gốc giữ nguyên trong upload, bản xem
là SOG nén bằng splat-transform qua port REC, publish bất biến theo nội dung.
"""

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.auth.models import DisplayName, Role
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads.models import UploadRecord
from src.services.reconstruction import extract_member, package_splat

logger = logging.getLogger(__name__)

ImportStatus = Literal["PACKAGING", "READY", "FAILED"]


class ImportedScene(BaseModel):
    """Một scene import; `delivery_ref` là SOG để trình duyệt nạp."""

    model_config = ConfigDict(extra="forbid")

    import_id: str
    upload_id: str
    name: str = Field(min_length=1, max_length=200)
    input_kind: Literal["gaussian_ply", "gaussian_ply_colmap"]
    status: ImportStatus
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

    def create(
        self,
        upload: UploadRecord,
        name: str,
        created_by: str | None,
        created_by_name: str | None = None,
        created_by_role: Role | None = None,
    ) -> ImportedScene:
        """Chỉ nhận upload đã nhận diện là 3DGS; bắt đầu ở PACKAGING."""
        if upload.input_kind not in {"gaussian_ply", "gaussian_ply_colmap"}:
            raise SceneImportError("Chỉ file 3DGS (.ply hoặc .zip PLY + COLMAP) mới import thành scene")
        record = ImportedScene(
            import_id=f"import-{uuid4().hex[:12]}",
            upload_id=upload.upload_id,
            name=name.strip() or upload.original_name,
            input_kind=upload.input_kind,  # type: ignore[arg-type]
            status="PACKAGING",
            created_at=datetime.now(UTC),
            created_by=created_by,
            created_by_name=created_by_name,
            created_by_role=created_by_role,
        )
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_imports(import_id, upload_id, payload) VALUES (?, ?, ?)",
                (record.import_id, record.upload_id, record.model_dump_json()),
            )
        return record

    def get(self, import_id: str) -> ImportedScene:
        """Đọc một import; không có → ImportNotFoundError."""
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_imports WHERE import_id=?", (import_id,)).fetchone()
        if row is None:
            raise ImportNotFoundError(f"không tìm thấy scene import: {import_id}")
        return ImportedScene.model_validate_json(row[0])

    def list(self) -> list[ImportedScene]:
        """Mới nhất trước."""
        with self.database.transaction() as tx:
            rows = tx.execute("SELECT payload FROM r2s_imports").fetchall()
        records = [ImportedScene.model_validate_json(row[0]) for row in rows]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def _update(self, record: ImportedScene, **changes: object) -> ImportedScene:
        """CAS theo trạng thái cũ để hai tác vụ nền không cùng ghi kết quả."""
        updated = record.model_copy(update=changes)
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_imports WHERE import_id=?" + tx.lock_suffix(), (record.import_id,)
            ).fetchone()
            if row is None or ImportedScene.model_validate_json(row[0]).status != record.status:
                raise RuntimeStateConflictError("scene import đã đổi trạng thái")
            tx.execute(
                "UPDATE r2s_imports SET payload=? WHERE import_id=?", (updated.model_dump_json(), record.import_id)
            )
        return updated

    def package(self, import_id: str, upload: UploadRecord, gpu_index: int | None) -> ImportedScene:
        """Nén PLY → SOG rồi publish; lỗi ghi FAILED với lý do hiển thị được."""
        record = self.get(import_id)
        if record.status != "PACKAGING":
            return record
        workspace = self.workspace_root / import_id / uuid4().hex
        workspace.mkdir(parents=True, exist_ok=False)
        try:
            source = self.resolver.require_uri(upload.artifact_uri, upload.checksum)
            if record.input_kind == "gaussian_ply_colmap":
                member = upload.detection.ply_member if upload.detection else None
                if member is None:
                    raise SceneImportError("Upload ZIP thiếu thông tin file PLY đã nhận diện")
                source = extract_member(source, member, workspace / "input.ply")
            sog = package_splat(source, workspace / "sog", gpu_index)
            payload = sog.read_bytes()
        except (ValueError, OSError) as error:
            logger.warning("Import %s packaging failed cause=%s", import_id, type(error).__name__)
            return self._update(record, status="FAILED", error="Không nén được scene 3DGS; kiểm file PLY rồi thử lại")
        digest = hashlib.sha256(payload).hexdigest()
        reference = ProductArtifactRef(
            artifact_type="VisualArtifact",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{import_id}/import/{digest}.sog",
            artifact_checksum=f"sha256:{digest}",
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.VISUAL_RECON,
            job_id=import_id,
            source_provenance={"visual_source": "user_import", "upload_checksum": upload.checksum},
        )
        FilesystemArtifactStore(self.resolver).publish(reference, payload)
        return self._update(record, status="READY", delivery_ref=reference, error=None)

    def content_path(self, import_id: str) -> Path:
        """Đường dẫn cục bộ SOG đã kiểm checksum (kéo từ kho file nếu cần)."""
        record = self.get(import_id)
        if record.delivery_ref is None:
            raise SceneImportError("Scene import chưa sẵn sàng")
        return self.resolver.require(record.delivery_ref)
