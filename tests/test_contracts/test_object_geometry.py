"""ObjectGS refs do not replace visual/collider identities or invalidate legacy checksums."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.object_geometry import (
    ObjectAwareEnvironmentManifest,
    ObjectShellManifest,
    ObjectSurfaceManifest,
)
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.scene import SceneIR


def scene() -> SceneIR:
    return SceneIR.model_validate_json((Path(__file__).parents[2] / "fixtures/scene_ir/scene.json").read_bytes())


def membership(value: SceneIR) -> ObjectMembershipArtifact:
    ref = value.environment.geometry_ref
    job_id = ref.artifact_uri.removeprefix("artifact://jobs/").partition("/")[0]
    ref = ref.model_copy(update={"job_id": job_id})
    return ObjectMembershipArtifact(
        source_visual_ref=ref.model_copy(update={"artifact_type": "GaussianPLY"}),
        source_geometry_ref=ref,
        extraction_revision=value.scene_revision,
        coordinate_system=value.coordinate_system,
        gaussian_count=10,
        labels_ref=ref.model_copy(update={"artifact_type": "ObjectMembershipLabels"}),
        label_to_object_id={"0": value.objects[0].id},
    )


def test_legacy_scene_dump_omits_new_optional_fields() -> None:
    value = scene().model_dump(mode="json")
    assert "object_aware_collision_ref" not in value["environment"]
    assert all("surface_mesh_ref" not in item for item in value["objects"])
    assert SceneIR.model_validate(value).model_dump(mode="json") == value


def test_surface_and_collider_are_separate_and_job_bound() -> None:
    value = scene()
    data = value.objects[0].model_dump(mode="json")
    surface = data["geometry_ref"] | {"artifact_type": "ObjectSurfaceMesh"}
    data["surface_mesh_ref"] = surface
    obj = type(value.objects[0]).model_validate(data)
    assert obj.surface_mesh_ref != obj.collider.geometry_ref
    for invalid in [
        surface | {"artifact_type": "ObjectCollider"},
        surface | {"artifact_uri": "artifact://jobs/other/a.glb", "job_id": "other"},
    ]:
        with pytest.raises(ValidationError):
            type(obj).model_validate(data | {"surface_mesh_ref": invalid})


def test_surface_receipt_requires_real_checkpoint_label_and_membership() -> None:
    value = scene()
    members = membership(value)
    ref = members.source_geometry_ref
    data = dict(
        object_id=value.objects[0].id,
        objectgs_label_id=1,
        surface_mesh_ref=ref.model_copy(update={"artifact_type": "ObjectSurfaceMesh"}),
        source_checkpoint_ref=ref.model_copy(update={"artifact_type": "ObjectGSCheckpoint"}),
        source_dataset_ref=ref.model_copy(update={"artifact_type": "ObjectGSDataset"}),
        source_membership=members,
        upstream_commit="a" * 40,
        canonical_world_from_training=value.objects[0].transform,
        vertex_count=8,
        triangle_count=12,
        quality={"watertight": True},
    )
    assert ObjectSurfaceManifest(**data).coordinate_frame == "object_local"
    for change in [
        {"objectgs_label_id": 256},
        {"objectgs_label_id": 0},
        {"upstream_commit": "main"},
        {"triangle_count": 0},
        {"object_id": "unknown"},
    ]:
        with pytest.raises(ValidationError):
            ObjectSurfaceManifest(**(data | change))


def test_object_aware_manifest_preserves_original_source_identity() -> None:
    value = scene()
    members = membership(value)
    ref = members.source_geometry_ref
    active = ref.model_copy(update={"artifact_type": "ObjectAwareEnvironmentCollision"})
    manifest = ObjectAwareEnvironmentManifest(
        source_geometry_ref=ref,
        collision_ref=active,
        source_membership=members,
        removed_object_ids=[value.objects[0].id],
        occupancy_checksum="sha256:" + "a" * 64,
        provenance={},
    )
    assert manifest.source_geometry_ref == ref
    data = value.environment.model_dump(mode="json")
    data.update(
        membership=members.model_dump(mode="json"),
        collider_ref=active.model_dump(mode="json"),
        object_aware_collision_ref=ref.model_copy(
            update={"artifact_type": "ObjectAwareEnvironmentManifest"}
        ).model_dump(mode="json"),
    )
    assert type(value.environment).model_validate(data).geometry_ref == value.environment.geometry_ref
    with pytest.raises(ValidationError, match="requires membership"):
        type(value.environment).model_validate(data | {"membership": None})
    with pytest.raises(ValidationError):
        ObjectAwareEnvironmentManifest.model_validate(manifest.model_dump() | {"removed_object_ids": ["missing"]})


def shell_data(value: SceneIR) -> dict:
    members = membership(value)
    ref = members.source_geometry_ref
    return dict(
        object_id=value.objects[0].id,
        shell_mesh_ref=ref.model_copy(update={"artifact_type": "ObjectShellMesh"}),
        source_membership=members,
        source_world_from_object=value.objects[0].transform,
        voxel_m=0.02,
        params={"opacity_min": 0.1, "outlier_k": 8, "outlier_std": 2.0, "close_iterations": 1},
        statistics={"gaussian_count": 10},
        quality={"passed": True},
        vertex_count=8,
        triangle_count=12,
    )


def test_shell_manifest_is_object_local_and_requires_passing_quality() -> None:
    value = scene()
    data = shell_data(value)
    assert ObjectShellManifest(**data).coordinate_frame == "object_local"
    wrong_job = data["shell_mesh_ref"].model_copy(update={"job_id": "other"})
    for change in [
        {"artifact_type": "ObjectSurfaceManifest"},
        {"object_id": "unknown"},
        {"quality": {"passed": False}},
        {"quality": {}},
        {"shell_mesh_ref": data["shell_mesh_ref"].model_copy(update={"artifact_type": "ObjectSurfaceMesh"})},
        {"shell_mesh_ref": wrong_job},
        {"voxel_m": 0},
        {"vertex_count": 3},
        {"triangle_count": 3},
    ]:
        with pytest.raises(ValidationError):
            ObjectShellManifest(**(data | change))


def test_scene_object_accepts_shell_surface_but_not_other_mesh_kinds() -> None:
    value = scene()
    data = value.objects[0].model_dump(mode="json")
    shell = data["geometry_ref"] | {"artifact_type": "ObjectShellMesh"}
    data["surface_mesh_ref"] = shell
    obj = type(value.objects[0]).model_validate(data)
    assert obj.surface_mesh_ref.artifact_type == "ObjectShellMesh"
    for invalid in [
        shell | {"artifact_type": "ObjectCollider"},
        shell | {"artifact_uri": "artifact://jobs/other/a.glb", "job_id": "other"},
    ]:
        with pytest.raises(ValidationError):
            type(obj).model_validate(data | {"surface_mesh_ref": invalid})
