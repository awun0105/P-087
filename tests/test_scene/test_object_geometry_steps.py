"""Shared geometry stages preserve object-local surfaces and immutable source ownership."""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.services.orchestration.scene import objectify as pipeline
from tests.test_scene.test_object_aware_geometry import ray


def reference(kind: str) -> pipeline.ProductArtifactRef:
    return pipeline._reference("job-steps", kind + "/{digest}", kind, pipeline.StageId.SCENE_DECOMPOSE, kind.encode())


@pytest.fixture
def environment_inputs() -> SimpleNamespace:
    # Missing floor under an extracted object must be restored by explicit inferred support.
    floor = np.array(
        [
            [x + 0.05, y + 0.05, 0.05]
            for x in (-0.2, -0.1, 0, 0.1, 0.2)
            for y in (-0.2, -0.1, 0, 0.1, 0.2)
            if not (x in (0, 0.1) and y in (0, 0.1))
        ]
    )
    object_points = np.array([[0.05, 0.05, 0.55], [0.15, 0.05, 0.55]])
    points = np.vstack([floor, object_points])
    labels = np.r_[np.full(len(floor), -1), [1, 1]].astype(np.int32)
    mapping = {"1": "candidate-001"}
    bundle = SimpleNamespace(canonical_geometry_ref=reference("CanonicalGeometry"))
    membership = ObjectMembershipArtifact(
        source_visual_ref=reference("GaussianPLY"),
        source_geometry_ref=bundle.canonical_geometry_ref,
        extraction_revision="rev-001",
        coordinate_system=CoordinateSystem(),
        gaussian_count=len(points),
        labels_ref=reference("ObjectMembershipLabels"),
        label_to_object_id=mapping,
    )
    published = {}

    def publish(ref: pipeline.ProductArtifactRef, payload: bytes) -> pipeline.ProductArtifactRef:
        published[ref.artifact_uri] = payload
        return ref

    arguments = dict(
        source_points=points,
        membership_labels=labels,
        label_to_object_id=mapping,
        footprints=[(np.array([0, 0, 0]), np.array([0.1, 0.1, 0.6]))],
        floor_model=SimpleNamespace(
            status="supported", plane_normal_world=(0, 0, 1), plane_offset_m=0, floor_band_m=0.02
        ),
        floor_fit={"fixture": True},
        voxel_m=0.1,
        bundle=bundle,
        membership=membership,
        publish=publish,
        job_id="job-steps",
    )
    return SimpleNamespace(arguments=arguments, published=published)


def test_environment_excludes_object_and_publishes_inferred_support(environment_inputs: SimpleNamespace) -> None:
    from src.services.orchestration.scene.object_geometry_steps import build_environment_collision

    collision, manifest_ref = build_environment_collision(**environment_inputs.arguments)
    mesh = trimesh.load(io.BytesIO(environment_inputs.published[collision.artifact_uri]), file_type="glb", force="mesh")
    assert mesh.is_watertight
    # First hit is inferred floor, never the object at z=0.55.
    assert ray(mesh, [0.05, 0.05, 1], [0, 0, -1]) == pytest.approx(0.9)
    manifest = json.loads(environment_inputs.published[manifest_ref.artifact_uri])
    assert manifest["removed_object_ids"] == ["candidate-001"]
    assert manifest["source_membership"] == environment_inputs.arguments["membership"].model_dump(mode="json")
    assert manifest["provenance"]["statistics"]["inferred_support_cells"] > 0
    assert manifest["provenance"]["inpaint_used_for_physics"] is False
    assert manifest["provenance"]["floor_fit"] == {"fixture": True}
    assert "/scene/objectgs/environment/" in collision.artifact_uri
    assert manifest_ref.producer_stage == pipeline.StageId.COLLIDER


@pytest.mark.parametrize("status", ["supported", "confirmed_prior_fallback", "uncertain"])
def test_environment_support_follows_floor_status(environment_inputs: SimpleNamespace, status: str) -> None:
    from src.services.orchestration.scene.object_geometry_steps import build_environment_collision

    environment_inputs.arguments["floor_model"].status = status
    _, manifest_ref = build_environment_collision(**environment_inputs.arguments)
    manifest = json.loads(environment_inputs.published[manifest_ref.artifact_uri])
    count = manifest["provenance"]["statistics"]["inferred_support_cells"]
    assert (count > 0) == (status != "uncertain")


def test_correction_support_keeps_original_source_contact_center(environment_inputs: SimpleNamespace) -> None:
    from src.services.orchestration.scene.object_geometry_steps import build_environment_collision

    arguments = environment_inputs.arguments
    arguments["floor_model"].plane_normal_world = (0.6, 0, 0.8)
    arguments["footprints"] = [(np.array([0, 0, 0]), np.array([2, 0.1, 0.6]))]
    _, default_ref = build_environment_collision(**arguments)
    default = json.loads(environment_inputs.published[default_ref.artifact_uri])
    assert default["provenance"]["statistics"]["inferred_support_cells"] == 0
    _, corrected_ref = build_environment_collision(**arguments, footprint_centers=[(0, 0, 0)])
    corrected = json.loads(environment_inputs.published[corrected_ref.artifact_uri])
    assert corrected["provenance"]["statistics"]["inferred_support_cells"] > 0


def test_environment_support_budget_fails_without_publication(environment_inputs: SimpleNamespace) -> None:
    from src.services.orchestration.scene.object_geometry_steps import build_environment_collision

    environment_inputs.arguments["footprints"] = [(np.array([-100, -100, 0]), np.array([100, 100, 1]))]
    with pytest.raises(pipeline.ObjectifyError, match="inferred support exceeds the geometry budget") as error:
        build_environment_collision(**environment_inputs.arguments)
    assert error.value.retryable is False
    assert not environment_inputs.published


@pytest.mark.parametrize("failure", ["zero_parts", "error", "missing_output", "missing_object"])
def test_surface_colliders_reject_incomplete_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from src.services.orchestration.scene.object_geometry_steps import SurfaceInput, run_surface_colliders

    output = tmp_path / "collider.glb"
    if failure != "missing_output":
        output.write_bytes(b"collider")
    item = {"id": "4", "parts": 0 if failure == "zero_parts" else 2}
    if failure == "error":
        item["error"] = "fixture failure"
    monkeypatch.setattr(
        pipeline, "_run", lambda *args, **kwargs: {"objects": [] if failure == "missing_object" else [item]}
    )
    inputs = [SurfaceInput("4", tmp_path / "surface.glb", "sha256:" + "a" * 64, output)]
    with pytest.raises(pipeline.ObjectifyError, match="Gaussian/OBB fallback is forbidden") as error:
        run_surface_colliders(tmp_path / "python", inputs, {}, tmp_path, 10, None)
    assert error.value.retryable is False


def test_surface_colliders_send_strict_local_mesh_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from threading import Event

    from src.services.orchestration.scene.object_geometry_steps import SurfaceInput, run_surface_colliders

    output = tmp_path / "collider.glb"
    output.write_bytes(b"collider")
    checksum = "sha256:" + "a" * 64
    cancel = Event()
    seen = {}

    def run(
        python: Path, script: Path, request: dict, workspace: Path, name: str, timeout: float, **kwargs: object
    ) -> dict:
        seen.update(request)
        assert script == pipeline.CONVEX_RUNNER
        assert name == "convex" and timeout == 10
        assert kwargs["cancel_event"] is cancel
        return {"objects": [{"id": "4", "parts": 2, "volume_m3": 0.2}]}

    monkeypatch.setattr(pipeline, "_run", run)
    actual = run_surface_colliders(
        tmp_path / "python",
        [SurfaceInput("4", tmp_path / "surface.glb", checksum, output)],
        {"threshold": 0.03},
        tmp_path,
        10,
        cancel,
    )
    assert actual == {"4": {"id": "4", "parts": 2, "volume_m3": 0.2}}
    assert seen == {
        "objects": [
            {
                "id": "4",
                "surface_mesh": str(tmp_path / "surface.glb"),
                "surface_checksum": checksum,
                "coordinate_frame": "object_local",
                "distance_unit": "m",
                "output_glb": str(output),
            }
        ],
        "config": {"threshold": 0.03},
    }
