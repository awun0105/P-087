"""Dịch vụ làm giàu dữ liệu vật lý (Physics Enrichment) cho SceneIR.

Gắn ColliderSpec và thông số vật lý trực tiếp vào SceneIR schema, nâng revision
và cập nhật scene_ir_checksum tuân thủ đúng TEAM_EXECUTION_CONTRACT.
"""

from typing import Any

from src.models.contracts.artifacts import JsonObject, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.scene import ColliderSpec, SceneEnvironment, SceneIR, SceneObject
from src.services.simulation.colliders.generator import (
    DEFAULT_GROUND_PLANE_THICKNESS_M,
    create_ground_plane_collider,
    generate_object_collider,
)

ENRICHMENT_PROVENANCE: dict[str, Any] = {
    "generator": "real2sim-physics-enrichment-v1.0",
    "producer_stage": "ST-PHYSICS-ENRICH",
}


def _resolve_next_revision(current_revision: str) -> str:
    """Sinh revision tiếp theo một cách tất định (deterministic)."""
    if current_revision.startswith("rev-") and current_revision[4:].isdigit():
        num = int(current_revision[4:]) + 1
        return f"rev-{num:03d}"
    return f"{current_revision}-phys"


def _build_collider_map(colliders: list[ColliderSpec] | None) -> dict[str, ColliderSpec]:
    """Tạo dictionary tra cứu collider, kiểm tra tính duy nhất của ID."""
    collider_map: dict[str, ColliderSpec] = {}
    if not colliders:
        return collider_map
    for col in colliders:
        if col.collider_id in collider_map:
            raise ValueError(f"Trùng lặp collider_id: {col.collider_id}")
        collider_map[col.collider_id] = col
        collider_map[col.local_transform.parent_frame] = col
    return collider_map


def _enrich_single_object(
    obj: SceneObject,
    collider_map: dict[str, ColliderSpec],
    auto_generate: bool,
) -> SceneObject:
    """Gắn hoặc sinh collider cho một SceneObject đơn lẻ."""
    if obj.id in collider_map:
        chosen_collider = collider_map[obj.id]
        if chosen_collider.local_transform.parent_frame != obj.local_frame:
            raise ValueError(
                f"Collider parent_frame '{chosen_collider.local_transform.parent_frame}' "
                f"không khớp với object.local_frame '{obj.local_frame}' của {obj.id}"
            )
        return obj.model_copy(update={"collider": chosen_collider})

    if obj.collider is not None:
        return obj

    if auto_generate:
        generated = generate_object_collider(obj)
        return obj.model_copy(update={"collider": generated})

    return obj


def _enrich_environment(
    env: SceneEnvironment,
    scene_id: str,
    world_frame: str,
    explicit_ref: ProductArtifactRef | None,
    add_ground_plane: bool,
) -> SceneEnvironment:
    """Gắn collider cho môi trường (hoặc tự sinh ground plane chuẩn hóa)."""
    if explicit_ref is not None:
        return env.model_copy(update={"collider_ref": explicit_ref})
    if env.collider_ref is None and add_ground_plane:
        gp_spec = create_ground_plane_collider(
            parent_frame=world_frame,
            dimensions_xyz_m=(100.0, 100.0, DEFAULT_GROUND_PLANE_THICKNESS_M),
        )
        gp_ref = ProductArtifactRef(
            artifact_type="ColliderGeometry",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{scene_id}/scene/floor_collider.json",
            artifact_checksum=canonical_content_checksum(gp_spec, "dimensions_xyz_m"),
            data_class="derived",
            producer_stage="ST-COLLIDER",
            job_id=scene_id,
        )
        return env.model_copy(update={"collider_ref": gp_ref})
    return env


def _build_and_seal_scene(
    base: SceneIR,
    revision: str,
    env: SceneEnvironment,
    objects: list[SceneObject],
    provenance: JsonObject,
) -> SceneIR:
    """Tạo SceneIR và đóng dấu checksum xác thực (sealed)."""
    temp_scene = SceneIR(
        artifact_type=base.artifact_type,
        schema_version=base.schema_version,
        scene_id=base.scene_id,
        scene_revision=revision,
        coordinate_system=base.coordinate_system,
        metric_scale=base.metric_scale,
        environment=env,
        objects=objects,
        provenance=provenance,
        scene_ir_checksum="sha256:" + "0" * 64,
    )
    new_checksum = canonical_content_checksum(temp_scene, "scene_ir_checksum")
    final_scene = temp_scene.model_copy(update={"scene_ir_checksum": new_checksum})
    verify_content_checksum(final_scene, "scene_ir_checksum")
    return final_scene


def enrich_scene_physics(
    scene: SceneIR,
    colliders: list[ColliderSpec] | None = None,
    new_revision: str | None = None,
    auto_generate_missing: bool = True,
    environment_collider_ref: ProductArtifactRef | None = None,
    add_ground_plane: bool = True,
    extra_provenance: JsonObject | None = None,
) -> SceneIR:
    """Làm giàu thông tin vật lý cho SceneIR và tạo revision mới có checksum hợp lệ."""
    col_map = _build_collider_map(colliders)
    objects = [_enrich_single_object(o, col_map, auto_generate_missing) for o in scene.objects]
    env = _enrich_environment(
        env=scene.environment,
        scene_id=scene.scene_id,
        world_frame=scene.coordinate_system.world_frame,
        explicit_ref=environment_collider_ref,
        add_ground_plane=add_ground_plane,
    )
    rev = new_revision or _resolve_next_revision(scene.scene_revision)
    prov = {
        **scene.provenance,
        **ENRICHMENT_PROVENANCE,
        "previous_revision": scene.scene_revision,
        **(extra_provenance or {}),
    }
    return _build_and_seal_scene(scene, rev, env, objects, prov)
