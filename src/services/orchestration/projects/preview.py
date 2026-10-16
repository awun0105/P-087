"""Resolve preview qua shared contract, không phụ thuộc SceneIR/Brush internals."""

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import JobManifest, StageId, StageStatus
from src.models.contracts.preview import ReconstructionPreview
from src.services.orchestration.artifacts import ArtifactChecksumError, ArtifactNotFoundError, ArtifactResolver


def load_job_preview(
    job: JobManifest, resolver: ArtifactResolver, *, reuse_verified_dependencies: bool = False
) -> ReconstructionPreview:
    """Chọn publication mới nhất trong journal; checksum lỗi không fallback bản cũ."""
    stages = [
        stage
        for stage in job.stage_artifacts
        if stage.artifact_type == "ReconstructionPreview" and stage.status == StageStatus.SUCCEEDED
    ]
    if not stages:
        raise ArtifactNotFoundError("Job chưa publish preview 3DGS")
    stage = stages[-1]
    if stage.stage_id != StageId.VISUAL_RECON or stage.artifact_uri is None or stage.artifact_checksum is None:
        raise ArtifactChecksumError("Preview publication thiếu identity")
    reference = ProductArtifactRef(
        artifact_type="ReconstructionPreview",
        schema_version="1.0",
        artifact_uri=stage.artifact_uri,
        artifact_checksum=stage.artifact_checksum,
        data_class=stage.data_class,
        producer_stage=stage.stage_id,
        job_id=job.job_id,
    )
    preview = resolver.load_model(reference, ReconstructionPreview)
    expected_uri = f"artifact://jobs/{job.job_id}/attempts/{preview.attempt_id}/rec11/preview.json"
    if (
        preview.job_id != job.job_id
        or preview.source_input_checksum != job.input_manifest_checksum
        or reference.artifact_uri != expected_uri
    ):
        raise ArtifactChecksumError("Preview không thuộc job/input/attempt đã publish")
    for dependency in (preview.source_visual_ref, preview.camera_pose_ref, preview.delivery_ref):
        if reuse_verified_dependencies:
            resolver.require_unchanged(dependency)
        else:
            resolver.require(dependency)
    return preview
