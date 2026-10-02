"""Xác nhận tỉ lệ mét cho scene Studio (REC-06 anchor + frame) — ranh giới EX-PRODUCT.

Người dùng chọn trên scene 3DGS: A/B, C/D, 3 điểm sàn và nhập khoảng cách thật; scene
dựng từ dataset mẫu có bản ghi hỗ trợ LiDAR thì khoảng cách lấy từ LiDAR (ADR 0004 §6).
Phần tính toán/bản ghi REC-06 đi qua port công khai `src.services.reconstruction`;
PRODUCT giữ authority: chỉ job đang chờ mới xác nhận được, quyết định ghi rõ ai xác
nhận đúng preview nào, rồi bản xác nhận bất biến được ghi vào JobManifest qua CAS.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import JobManifest, StageId
from src.models.contracts.preview import ReconstructionPreview
from src.services.orchestration.artifacts import ArtifactStoreError, FilesystemArtifactStore, sha256_file
from src.services.orchestration.jobs.progress import awaiting_metric_confirmation, metric_confirmation_stage
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction import (
    DemoSelection,
    LidarMeasurements,
    MetricProposal,
    ModeComparison,
    UserMetricInput,
    UserMetricPreview,
    confirmation_summary,
    lidar_support_uri,
    publish_json,
    user_metric_port,
)

Point = tuple[float, float, float]

#: Ngưỡng cảnh báo (không chặn): người dùng tự quyết sau khi xem số liệu.
FLOOR_RESIDUAL_WARN_M = 0.05
CAMERA_HEIGHT_RANGE_M = (0.2, 4.0)


class MetricDecision(BaseModel):
    """Quyết định xác nhận của người dùng cho đúng một preview (authority của REC-06)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["MetricConfirmationDecision"] = "MetricConfirmationDecision"
    job_id: str
    preview_checksum: str
    decided_by: str | None
    decided_role: Literal["editor", "reviewer"] | None
    decided_at: datetime


class MetricPreviewView(UserMetricPreview):
    """Số liệu xem trước + cảnh báo cho UI."""

    warnings: list[str]


class MetricConfirmationError(ValueError):
    """Đầu vào/trạng thái không hợp lệ; message hiển thị được cho người dùng."""


class MetricConfirmationService:
    """Một request một instance; state nằm ở artifact store + JobManifest."""

    def __init__(self, registry: ProjectRegistry) -> None:
        self.registry = registry
        self.writer = FilesystemArtifactStore(registry.runtime_resolver)
        self.port = user_metric_port(
            registry.runtime_resolver.require, self.writer, self._exists, registry.runtime_resolver.locate
        )

    def _exists(self, artifact_uri: str) -> bool:
        return self.registry.runtime_resolver.locate(artifact_uri) is not None

    def _waiting_job(self, job_id: str) -> tuple[JobManifest, ReconstructionPreview]:
        job = self.registry.get_job(job_id)
        try:
            preview = self.registry.get_preview(job_id)
        except (ArtifactStoreError, ValueError) as error:
            raise MetricConfirmationError("Scene chưa có preview 3DGS") from error
        if not awaiting_metric_confirmation(job, True):
            raise MetricConfirmationError("Scene không ở bước chờ xác nhận tỉ lệ mét")
        return job, preview

    def lidar_support(self, job_id: str) -> ProductArtifactRef | None:
        """Bản ghi hỗ trợ LiDAR của job (dataset mẫu); None với video người dùng.

        Bản ghi do bước chuẩn bị offline publish tại URI cố định; checksum tính từ bytes
        đang có, port REC kiểm tiếp căn chỉnh/LiDAR/camera pose bên trong.
        """
        path = self.registry.runtime_resolver.locate(lidar_support_uri(job_id))
        if path is None:
            return None
        return ProductArtifactRef(
            artifact_type="DemoLidarSupport",
            schema_version="1.0",
            artifact_uri=lidar_support_uri(job_id),
            artifact_checksum=sha256_file(path),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.RGB_LIDAR_ALIGN,
            job_id=job_id,
        )

    def lidar_measurements(
        self, job_id: str, anchor: tuple[Point, Point], check: tuple[Point, Point]
    ) -> LidarMeasurements:
        """Khoảng cách LiDAR cho A/B và C/D để UI điền sẵn (chỉ scene có hỗ trợ LiDAR)."""
        _, contract = self._waiting_job(job_id)
        try:
            return self.port.lidar_measurements(
                job_id, contract.source_visual_ref, self.lidar_support(job_id), anchor, check
            )
        except ValueError as error:
            raise MetricConfirmationError(str(error)) from error

    def comparison(self, job_id: str) -> ModeComparison:
        """Ba hướng tỉ lệ trên cùng scene (demo so sánh); cần preview, không cần đang chờ."""
        job = self.registry.get_job(job_id)
        try:
            contract = self.registry.get_preview(job_id)
        except (ArtifactStoreError, ValueError) as error:
            raise MetricConfirmationError("Scene chưa có preview 3DGS") from error
        stage = metric_confirmation_stage(job)
        confirmation = None
        if stage is not None and stage.artifact_uri is not None and stage.artifact_checksum is not None:
            confirmation = confirmation_summary(
                stage.artifact_uri, stage.artifact_checksum, job_id, self.registry.runtime_resolver.require
            ).reference
        try:
            return self.port.mode_comparison(
                job_id, contract.source_visual_ref, confirmation, self.lidar_support(job_id)
            )
        except ValueError as error:
            raise MetricConfirmationError(str(error)) from error

    def auto_proposal(self, job_id: str) -> MetricProposal | None:
        """Đề xuất tỉ lệ/mặt sàn tự động của scene (ESTIMATED); None khi worker không tạo.

        Chỉ cần scene có preview: đề xuất là số liệu để xem, không đổi trạng thái job.
        """
        try:
            contract = self.registry.get_preview(job_id)
        except (ArtifactStoreError, ValueError) as error:
            raise MetricConfirmationError("Scene chưa có preview 3DGS") from error
        try:
            return self.port.auto_proposal(job_id, contract.source_visual_ref)
        except ValueError as error:
            raise MetricConfirmationError(str(error)) from error

    def demo_selection(self, job_id: str) -> DemoSelection:
        """Dataset mẫu: 7 điểm tự chọn từ LiDAR + số đo, để UI vẽ và điền sẵn."""
        _, contract = self._waiting_job(job_id)
        try:
            return self.port.demo_selection(job_id, contract.source_visual_ref, self.lidar_support(job_id))
        except ValueError as error:
            raise MetricConfirmationError(str(error)) from error

    def preview(self, job_id: str, data: UserMetricInput) -> MetricPreviewView:
        """Tính trước, chưa xác nhận; kèm cảnh báo để người dùng tự kiểm."""
        _, contract = self._waiting_job(job_id)
        try:
            summary = self.port.preview(job_id, contract.source_visual_ref, data, self.lidar_support(job_id))
        except ValueError as error:
            raise MetricConfirmationError(str(error)) from error
        warnings: list[str] = []
        if summary.floor_residual_m > FLOOR_RESIDUAL_WARN_M:
            warnings.append(f"3 điểm sàn lệch nhau {summary.floor_residual_m:.2f} m; nên chọn lại trên mặt sàn phẳng")
        low, high = CAMERA_HEIGHT_RANGE_M
        if summary.camera_height_min_m < low or summary.camera_height_max_m > high:
            warnings.append(
                f"Độ cao camera suy ra {summary.camera_height_min_m:.2f}–{summary.camera_height_max_m:.2f} m "
                "bất thường; kiểm lại điểm chọn hoặc khoảng cách"
            )
        if summary.distance_source == "ai_estimated":
            proposal = self.auto_proposal(job_id)
            margin = f" (sai số ước tính ±{proposal.relative_uncertainty * 100:.0f}%)" if proposal is not None else ""
            warnings.append(
                f"Khoảng cách là ước lượng tự động từ ảnh{margin}, không phải số đo ngoài đời; "
                "đoạn kiểm C–D dùng cùng ước lượng nên không kiểm được sai số. Đo thật một đoạn để chính xác hơn"
            )
        return MetricPreviewView(**summary.model_dump(), warnings=warnings)

    def confirm(
        self,
        job_id: str,
        data: UserMetricInput,
        preview_checksum: str,
        decided_by: str | None,
        decided_role: Literal["editor", "reviewer"] | None,
        require_identity: bool,
    ) -> ProductArtifactRef:
        """Xác nhận đúng preview người dùng đã xem; publish bản ghi và ghi vào job."""
        job, contract = self._waiting_job(job_id)
        if require_identity and decided_by is None:
            raise MetricConfirmationError("Cần đăng nhập để xác nhận tỉ lệ")
        decision = MetricDecision(
            job_id=job_id,
            preview_checksum=preview_checksum,
            decided_by=decided_by,
            decided_role=decided_role,
            decided_at=datetime.now(UTC),
        )
        decision_ref = publish_json(self.writer, self._exists, job_id, "decisions", decision, decision.artifact_type)

        def verify(checked_preview: str, reference: ProductArtifactRef) -> bool:
            """Decision đúng job, đúng preview, có người xác nhận khi deployment bắt đăng nhập."""
            stored = MetricDecision.model_validate_json(self.registry.runtime_resolver.require(reference).read_bytes())
            return (
                stored.job_id == job_id
                and stored.preview_checksum == checked_preview
                and (stored.decided_by is not None or not require_identity)
            )

        try:
            reference = self.port.confirm(
                job_id,
                contract.source_visual_ref,
                data,
                preview_checksum,
                decision_ref,
                verify,
                self.lidar_support(job_id),
            )
        except ValueError as error:
            raise MetricConfirmationError(str(error)) from error
        self.registry.record_metric_confirmation(job, reference)
        return reference
