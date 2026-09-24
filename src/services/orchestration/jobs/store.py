"""Persist JobManifest revisions as immutable artifacts.

Mỗi lần chuyển trạng thái publish một revision mới ở URI riêng, nên revision cũ
không thể bị ghi đè: `FilesystemArtifactStore.publish` từ chối path đã tồn tại.
"""

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef
from src.models.contracts.manifests import JobManifest
from src.services.orchestration.artifacts import (
    ArtifactResolver,
    FilesystemArtifactStore,
    sha256_bytes,
)

_SCHEMA_VERSION = "1.0"
_ARTIFACT_TYPE = "JobManifest"


class JobArtifactStore:
    """Publish and re-read immutable JobManifest revisions."""

    def __init__(self, resolver: ArtifactResolver) -> None:
        self.resolver = resolver
        self.artifacts = FilesystemArtifactStore(resolver)

    @staticmethod
    def manifest_uri(job_id: str, sequence: int) -> str:
        """URI revision thứ `sequence` (1-based) của một job."""
        return f"artifact://jobs/{job_id}/manifests/job_manifest.{sequence:03d}.json"

    def publish_manifest(self, manifest: JobManifest, sequence: int) -> ArtifactRef:
        """Ghi một revision bất biến và trả ref đã kiểm checksum."""
        payload = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
        reference = ArtifactRef(
            artifact_type=_ARTIFACT_TYPE,
            schema_version=_SCHEMA_VERSION,
            artifact_uri=self.manifest_uri(manifest.job_id, sequence),
            artifact_checksum=sha256_bytes(payload),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=manifest.current_stage,
            job_id=manifest.job_id,
        )
        self.artifacts.publish(reference, payload)
        return reference

    def load_manifest(self, reference: ArtifactRef) -> JobManifest:
        """Đọc lại một revision đã publish, có xác minh checksum byte."""
        return self.resolver.load_model(reference, JobManifest)
