"""Source ownership mapping for explicitly selected collision candidates."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.scene import SceneIR, SceneObject, SourceCollisionRegion
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.scene.collision_source_selection import (
    _map_lidar_ownership,
    select_lidar_collision_candidate,
)
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.errors import SceneRevisionConflictError

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _candidate_ref(payload: bytes | None = None) -> ProductArtifactRef:
    payload = payload or _candidate_mesh()
    return ProductArtifactRef.model_validate(
        {
            "artifact_type": "LidarCollisionCandidate",
            "schema_version": "1.0",
            "artifact_uri": "artifact://jobs/job-fixture-001/collider/lidar.glb",
            "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "data_class": "derived",
            "producer_stage": "ST-COLLIDER",
            "job_id": "job-fixture-001",
        }
    )


def _candidate_mesh() -> bytes:
    vertices = np.asarray(
        [
            [0.8, 1.8, 0.1],
            [1.2, 1.8, 0.1],
            [1.0, 2.2, 0.1],
            [0.8, 1.8, 0.3],
            [1.2, 1.8, 0.3],
            [1.0, 2.2, 0.3],
        ],
        dtype=np.float64,
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray([[0, 1, 2], [3, 4, 5]]), process=False)
    return mesh.export(file_type="glb")


def _scene_with_source_regions(*, overlap: bool = False) -> SceneIR:
    scene = SceneIR.model_validate_json((FIXTURES / "scene_ir/scene.json").read_text(encoding="utf-8"))
    source_object = scene.objects[0]
    objects: list[SceneObject] = []
    for object_id in (source_object.id, "object-overlap") if overlap else (source_object.id,):
        item = source_object
        if object_id != source_object.id:
            transform = source_object.transform.model_copy(update={"local_frame": object_id})
            item = source_object.model_copy(update={"id": object_id, "local_frame": object_id, "transform": transform})
        region = SourceCollisionRegion(
            object_id=object_id,
            source_geometry_ref=scene.environment.geometry_ref,
            extraction_revision=scene.scene_revision,
            source_transform=item.transform,
            region_kind="source_obb",
            source_obb_dimensions_xyz_m=(2.0, 2.0, 2.0),
        )
        objects.append(item.model_copy(update={"source_collision": region}, deep=True))
    return scene.model_copy(update={"objects": objects}, deep=True)


def test_lidar_ownership_maps_faces_on_candidate_not_rgb_mesh() -> None:
    scene = _scene_with_source_regions()
    mesh_bytes = _candidate_mesh()
    source_ref = _candidate_ref(mesh_bytes)
    manifest = SimpleNamespace(candidate_ref=source_ref)

    memberships, report, blockers = _map_lidar_ownership(scene, manifest, mesh_bytes)

    assert blockers == []
    assert report.source_ref == source_ref
    assert report.triangle_count == 2
    assert report.regions[0].candidate_triangle_count == 2
    assert report.regions[0].owned_triangle_count == 2
    assert memberships == {scene.objects[0].id: [0, 1]}


def test_lidar_ownership_reports_ambiguous_candidate_faces() -> None:
    scene = _scene_with_source_regions(overlap=True)
    mesh_bytes = _candidate_mesh()

    memberships, report, blockers = _map_lidar_ownership(
        scene,
        SimpleNamespace(candidate_ref=_candidate_ref(mesh_bytes)),
        mesh_bytes,
    )

    assert memberships == {scene.objects[0].id: [], "object-overlap": []}
    assert report.ambiguous_triangle_count == 2
    assert all(row.ambiguous_triangle_count == 2 for row in report.regions)
    assert len(blockers) == 2


def test_selection_rejects_stale_scene_revision_before_resolving_candidate(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "artifacts")
    editor = SceneEditor(FIXTURES, resolver)

    with pytest.raises(SceneRevisionConflictError, match="scene đã đổi"):
        select_lidar_collision_candidate(
            editor,
            "job-fixture-001",
            "rev-stale",
            _candidate_ref().model_copy(
                update={
                    "artifact_type": "LidarCollisionCandidateManifest",
                    "artifact_uri": "artifact://jobs/job-fixture-001/collider/lidar-candidate/manifest.json",
                }
            ),
        )
