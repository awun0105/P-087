"""Consumer checkpoint preview: kiểm lại exact bytes, request/config và lineage qua store."""

from typing import TYPE_CHECKING

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.services.reconstruction.attempt import PublicationNamespace
from src.services.reconstruction.preview_models import PreparedPreviewRequest, PreparedPreviewResult
from src.services.reconstruction.rgb.frame_set import _sha256
from src.services.reconstruction.rgb.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.visual_publication import VisualResolver

if TYPE_CHECKING:
    from src.services.reconstruction.preview_worker import PreviewDependencies


def _read(reference: ProductArtifactRef, deps: "PreviewDependencies") -> bytes:
    path = deps.resolve(reference)
    if _sha256(path) != reference.artifact_checksum:
        raise ValueError("preview dependency byte checksum mismatch")
    return path.read_bytes()


def load_preview(reference: ProductArtifactRef, deps: "PreviewDependencies") -> PreparedPreviewResult:
    """Success checkpoint chỉ hợp lệ khi source/output còn resolve và cùng attempt."""
    if reference.artifact_type != "PreparedPreviewResult":
        raise ValueError("not a prepared preview result")
    result = PreparedPreviewResult.model_validate_json(_read(reference, deps))
    request = PreparedPreviewRequest.model_validate_json(_read(result.request_ref, deps))
    namespace = PublicationNamespace(job_id=request.job_id, attempt_id=request.attempt_id)
    if (result.job_id, result.attempt_id, result.source_input_checksum) != (
        request.job_id,
        request.attempt_id,
        request.source_input_checksum,
    ):
        raise ValueError("preview checkpoint differs from attempt request")
    _record_identity(reference, namespace, "result.json")
    _record_identity(result.request_ref, namespace, "request.json")
    if result.preview_complete:
        _validate_outputs(request, result, deps)
    return result


def _record_identity(reference: ProductArtifactRef, namespace: PublicationNamespace, name: str) -> None:
    if reference.job_id != namespace.job_id or reference.artifact_uri != namespace.uri("rec11", name):
        raise ValueError("preview record belongs to a different job/attempt")
    if reference.source_provenance != {"execution_scope": "prepared_rgb_preview", **namespace.provenance()}:
        raise ValueError("preview record provenance differs from attempt")


def _validate_outputs(
    request: PreparedPreviewRequest, result: PreparedPreviewResult, deps: "PreviewDependencies"
) -> None:
    frames = deps.frames.load(request.frame_set_ref)
    if frames.input_manifest_checksum != request.source_input_checksum:
        raise ValueError("preview source identity mismatch")
    deps.frames.materialize(frames)
    poses = CameraPoseResolver(deps.resolve, deps.frames)
    visual = VisualResolver(deps.resolve, poses).load(result.raw_visual_ref)
    pose = poses.load(result.camera_pose_ref)
    if pose.source_frame_set != request.frame_set_ref or pose.config != request.colmap:
        raise ValueError("preview poses differ from requested source/config")
    if visual.source_camera_poses != result.camera_pose_ref or visual.config != request.brush:
        raise ValueError("preview visual differs from requested poses/config")
    if visual.delivery != result.delivery_ref:
        raise ValueError("preview delivery differs from visual manifest")
    namespace = PublicationNamespace(job_id=request.job_id, attempt_id=request.attempt_id)
    for ref, stage in (
        (result.camera_pose_ref, "rec03"),
        (result.raw_visual_ref, "rec04"),
        (result.delivery_ref, "rec04"),
    ):
        if ref.job_id != request.job_id or not ref.artifact_uri.startswith(
            namespace.uri(stage, "payload").removesuffix("payload")
        ):
            raise ValueError("preview output belongs to another job/attempt")
    _validate_stages(result)


def _validate_stages(result: PreparedPreviewResult) -> None:
    for stage, ref, expected in zip(
        result.stage_artifacts,
        (result.camera_pose_ref, result.raw_visual_ref),
        (StageId.CAMERA_POSE, StageId.VISUAL_RECON),
        strict=True,
    ):
        if stage.status != "SUCCEEDED" or stage.stage_id != expected:
            raise ValueError("preview stage was not completed")
        if (stage.artifact_uri, stage.artifact_checksum, stage.artifact_type, stage.data_class) != (
            ref.artifact_uri,
            ref.artifact_checksum,
            ref.artifact_type,
            ref.data_class,
        ):
            raise ValueError("preview stage differs from published output")
