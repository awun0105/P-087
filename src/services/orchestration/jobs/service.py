"""Job lifecycle service: validate, build the next revision, persist it.

PRODUCT-02 §3: stage dài không được mô hình hoá bằng một HTTP request hay bằng
thành công giả. Vì vậy `SUCCEEDED` chỉ được ghi khi artifact đầu ra thật sự
resolve được và khớp checksum.
"""

from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ArtifactRef
from src.models.contracts.manifests import JobManifest, JobStatus, StageArtifact
from src.services.orchestration.artifacts import ArtifactResolver, with_canonical_checksum
from src.services.orchestration.artifacts.errors import ArtifactNotFoundError, ArtifactStoreError
from src.services.orchestration.jobs.errors import JobNotResolvableError
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.store import JobArtifactStore
from src.services.orchestration.jobs.transitions import CLOSING_STATUSES, require_transition


class JobLifecycle:
    """Apply one legal transition and publish the resulting revision."""

    def __init__(self, resolver: ArtifactResolver, fixture_resolver: ArtifactResolver | None = None) -> None:
        """`resolver` là root ghi được lúc chạy; `fixture_resolver` là root chỉ đọc
        chứa artifact mẫu, để job mẫu vẫn kiểm chứng được trước khi có worker thật."""
        self.resolver = resolver
        self.fixture_resolver = fixture_resolver
        self.store = JobArtifactStore(resolver)

    def _require(self, reference: ArtifactRef) -> Path:
        """Resolve trong root chính, chỉ rơi sang root fixture khi KHÔNG TÌM THẤY.

        Checksum lệch là lỗi toàn vẹn dữ liệu, không phải chuyện artifact nằm ở đâu
        — nên nó fail closed, không được thử root khác rồi cho qua.
        """
        try:
            return self.resolver.require(reference)
        except ArtifactNotFoundError:
            if self.fixture_resolver is None:
                raise
            return self.fixture_resolver.require(reference)

    def persist_initial(self, manifest: JobManifest) -> ArtifactRef:
        """Ghi revision đầu tiên của một job vừa tạo, để attempt 1 có provenance."""
        return self.store.publish_manifest(manifest, 1)

    def apply(self, current: JobManifest, request: TransitionRequest, sequence: int) -> tuple[JobManifest, ArtifactRef]:
        """Trả về manifest mới và ref của revision vừa publish."""
        updated = self.prepare(current, request)
        return updated, self.store.publish_manifest(updated, sequence)

    def prepare(self, current: JobManifest, request: TransitionRequest) -> JobManifest:
        """Validate trước publication; persistence chịu trách nhiệm CAS con trỏ."""
        require_transition(current.status, request.target_status)
        if request.target_status == JobStatus.SUCCEEDED:
            self.require_artifacts_resolvable(current)
        return self._build_revision(current, request)

    def require_artifacts_resolvable(self, manifest: JobManifest) -> None:
        """Chặn ghi SUCCEEDED khi job chưa có artifact đầu ra kiểm chứng được."""
        published = [stage for stage in manifest.stage_artifacts if self._is_published(stage)]
        if not published:
            raise JobNotResolvableError(
                f"job {manifest.job_id} chưa có artifact nào được publish; không thể ghi SUCCEEDED"
            )
        for stage in published:
            try:
                self._require(_as_reference(manifest.job_id, stage))
            except ArtifactStoreError as error:
                raise JobNotResolvableError(
                    f"artifact của stage {stage.stage_id} không resolve được: {error}"
                ) from error

    @staticmethod
    def _is_published(stage: StageArtifact) -> bool:
        """Một stage chỉ được coi là đã publish khi có đủ URI và checksum byte."""
        return stage.artifact_uri is not None and stage.artifact_checksum is not None and stage.data_class is not None

    @staticmethod
    def _build_revision(current: JobManifest, request: TransitionRequest) -> JobManifest:
        """Dựng revision kế tiếp; không bao giờ sửa `started_at` hay stage cũ."""
        update = {
            "status": request.target_status,
            "current_stage": request.current_stage or current.current_stage,
            "completed_at": datetime.now(UTC) if request.target_status in CLOSING_STATUSES else None,
        }
        return with_canonical_checksum(current.model_copy(update=update), "job_manifest_checksum")


def _as_reference(job_id: str, stage: StageArtifact) -> ArtifactRef:
    """Chiếu một stage artifact đã publish thành ArtifactRef để resolver kiểm tra."""
    return ArtifactRef(
        artifact_type=stage.artifact_type or "unknown",
        schema_version="1.0",
        artifact_uri=stage.artifact_uri,
        artifact_checksum=stage.artifact_checksum,
        data_class=stage.data_class,
        producer_stage=stage.stage_id,
        job_id=job_id,
    )
