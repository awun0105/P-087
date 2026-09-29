"""Build and validate SceneIR revisions from EX-SCENE domain outputs."""

from src.models.contracts.coordinates import Transform
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.scene import (
    SceneEnvironment,
    SceneIR,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
)
from src.services.scene.bundle_consumer import ValidatedBundleView
from src.services.scene.decomposition.models import DecompositionResult, ObjectBinding

_ZERO_CHECKSUM = "sha256:" + "0" * 64


def build_scene_ir(decomposition: DecompositionResult, view: ValidatedBundleView) -> SceneIR:
    """Build a checksummed SceneIR from decomposition bindings."""
    scene = SceneIR(
        artifact_type="SceneIR",
        schema_version="1.0",
        scene_id=f"scene-{view.bundle.job_id}",
        scene_revision="rev-001",
        coordinate_system=view.bundle.coordinate_system,
        metric_scale=view.bundle.metric_scale,
        environment=SceneEnvironment(
            visual_ref=decomposition.visual_ref,
            geometry_ref=decomposition.environment_geometry_ref,
        ),
        objects=[_scene_object(binding) for binding in decomposition.object_bindings],
        provenance=decomposition.provenance,
        scene_ir_checksum=_ZERO_CHECKSUM,
    )
    return with_scene_checksum(scene)


def with_scene_checksum(scene: SceneIR) -> SceneIR:
    """Return the same SceneIR content with canonical checksum refreshed."""
    payload = scene.model_copy(update={"scene_ir_checksum": _ZERO_CHECKSUM}, deep=True)
    checksum = canonical_content_checksum(payload, "scene_ir_checksum")
    checked = payload.model_copy(update={"scene_ir_checksum": checksum}, deep=True)
    verify_content_checksum(checked, "scene_ir_checksum")
    return checked


def _scene_object(binding: ObjectBinding) -> SceneObject:
    transform = _identity_transform(binding.object_id)
    return SceneObject(
        id=binding.object_id,
        name=binding.name,
        state=SceneObjectState.CONFIRMED,
        origin=SceneObjectOrigin.RECONSTRUCTED,
        active=True,
        local_frame=binding.object_id,
        transform=transform,
        geometry_ref=binding.geometry_ref,
        provenance=binding.provenance,
    )


def _identity_transform(local_frame: str) -> Transform:
    return Transform(
        parent_frame="world",
        local_frame=local_frame,
        translation_xyz=(0.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
