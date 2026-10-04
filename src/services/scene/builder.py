"""Dựng SceneIR đầu tiên của một job từ ReconstructionBundle thật (EX-SCENE)."""

from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import SceneEnvironment, SceneIR, SceneObject
from src.services.scene.publisher import with_scene_checksum

_ZERO_CHECKSUM = "sha256:" + "0" * 64


def scene_from_bundle(
    bundle: ReconstructionBundle,
    objects: list[SceneObject],
    provenance: dict,
    environment: SceneEnvironment | None = None,
) -> SceneIR:
    """Môi trường = 3DGS hệ mét + collision mesh REC-05; vật thể = ứng viên chờ xác nhận.

    `environment` thay môi trường mặc định khi bước tách theo vật (pipeline v2) đã dựng nền đã vá.
    """
    scene = SceneIR(
        artifact_type="SceneIR",
        schema_version="1.0",
        scene_id=f"scene-{bundle.job_id}",
        scene_revision="rev-001",
        coordinate_system=bundle.coordinate_system,
        metric_scale=bundle.metric_scale,
        environment=environment
        or SceneEnvironment(
            visual_ref=bundle.visual_artifact_ref,
            geometry_ref=bundle.canonical_geometry_ref,
        ),
        objects=objects,
        provenance={"bundle_checksum": bundle.artifact_checksum, **provenance},
        scene_ir_checksum=_ZERO_CHECKSUM,
    )
    return with_scene_checksum(scene)
