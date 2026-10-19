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


@pytest.mark.parametrize("origin", ["objectgs", "gaussian_shell"])
def test_surface_colliders_send_strict_local_mesh_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
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
        surface_origin=origin,
    )
    assert actual == {"4": {"id": "4", "parts": 2, "volume_m3": 0.2}}
    assert seen == {
        "objects": [
            {
                "id": "4",
                "surface_mesh": str(tmp_path / "surface.glb"),
                "surface_checksum": checksum,
                "surface_origin": origin,
                "coordinate_frame": "object_local",
                "distance_unit": "m",
                "output_glb": str(output),
            }
        ],
        "config": {"threshold": 0.03},
    }


def test_inpaint_packages_and_publishes_original_background_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from src.services.orchestration.scene.object_geometry_steps import run_inpaint_and_package

    events = []
    cancel = Event()
    settings = SimpleNamespace(product_lama_checkpoint=tmp_path / "lama.pt", product_geometry_gpu_index=2)
    background, objects = tmp_path / "background.ply", tmp_path / "objects_world.ply"
    views = [{"image_path": "frame.png"}]
    result = {"method": "fixture", "original_gaussians": 5, "inpainted_gaussians": 3}

    def run(
        python: Path, script: Path, request: dict, workspace: Path, name: str, timeout: float, **kwargs: object
    ) -> dict:
        events.append("inpaint")
        assert script == pipeline.INPAINT_RUNNER and name == "inpaint"
        assert timeout == 10 and kwargs["cancel_event"] is cancel
        assert request == {
            "background_ply": str(background),
            "objects_ply": str(objects),
            "output_ply": str(tmp_path / "background_inpainted.ply"),
            "lama_checkpoint": str(settings.product_lama_checkpoint),
            "views": views,
            "config": {"max_new_gaussians": 100},
        }
        (workspace / "background_inpainted.ply").write_bytes(b"background")
        return result

    def package(source: Path, workspace: Path, device: int, **kwargs: object) -> Path:
        events.append("package")
        assert source == tmp_path / "background_inpainted.ply"
        assert workspace == tmp_path / "sog" and device == 2
        assert kwargs["cancel_event"] is cancel
        sog = tmp_path / "background.sog"
        sog.write_bytes(b"sog")
        return sog

    def prepare() -> None:
        events.append("membership")

    def publish(ref: pipeline.ProductArtifactRef, payload: bytes) -> pipeline.ProductArtifactRef:
        events.append(ref.artifact_type)
        expected = "GaussianPLY" if payload == b"background" else "VisualArtifact"
        tail = "background.ply" if payload == b"background" else "background.sog"
        assert ref == pipeline._reference(
            "job-steps", "environment/{digest}/" + tail, expected, pipeline.StageId.SCENE_DECOMPOSE, payload
        )
        return ref

    monkeypatch.setattr(pipeline, "_run", run)
    monkeypatch.setattr(pipeline, "package_splat", package)
    master, visual, actual = run_inpaint_and_package(
        tmp_path / "python",
        background_ply=background,
        objects_ply=objects,
        views=views,
        settings=settings,
        inpaint_config={"max_new_gaussians": 100},
        workspace=tmp_path,
        timeout=10,
        cancel_event=cancel,
        publish=publish,
        job_id="job-steps",
        before_publish=prepare,
    )
    assert actual == result
    assert master.artifact_type == "GaussianPLY" and visual.artifact_type == "VisualArtifact"
    assert events == ["inpaint", "package", "membership", "GaussianPLY", "VisualArtifact"]


@pytest.mark.parametrize("error_type", [ValueError, OSError])
def test_package_error_preserves_message_and_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    from src.services.orchestration.scene.object_geometry_steps import run_inpaint_and_package

    def fail(*args: object, **kwargs: object) -> None:
        raise error_type("fixture failure")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Precomputed inpaint must not rerun; failed package must not publish")

    monkeypatch.setattr(pipeline, "_run", forbidden)
    monkeypatch.setattr(pipeline, "package_splat", fail)
    with pytest.raises(pipeline.ObjectifyError, match="nén SOG nền lỗi: fixture failure"):
        run_inpaint_and_package(
            tmp_path / "python",
            background_ply=tmp_path / "background.ply",
            objects_ply=tmp_path / "objects.ply",
            views=[],
            settings=SimpleNamespace(product_geometry_gpu_index=0),
            inpaint_config={},
            workspace=tmp_path,
            timeout=10,
            cancel_event=None,
            publish=forbidden,
            job_id="job-steps",
            inpaint_result={"method": "fixture"},
            before_publish=forbidden,
        )


def test_precomputed_inpaint_is_packaged_once_and_cancellation_blocks_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from src.services.orchestration.scene.object_geometry_steps import run_inpaint_and_package
    from src.services.process_control import ProcessCancelledError

    cancel = Event()
    packaged = []

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("No repeated inpaint or background publication after cancellation")

    def package(*args: object, **kwargs: object) -> Path:
        packaged.append(True)
        assert kwargs["cancel_event"] is cancel
        cancel.set()
        return tmp_path / "unused.sog"

    monkeypatch.setattr(pipeline, "_run", forbidden)
    monkeypatch.setattr(pipeline, "package_splat", package)
    with pytest.raises(ProcessCancelledError, match="Objectify operation was cancelled"):
        run_inpaint_and_package(
            tmp_path / "python",
            background_ply=tmp_path / "background.ply",
            objects_ply=tmp_path / "objects.ply",
            views=[],
            settings=SimpleNamespace(product_geometry_gpu_index=0),
            inpaint_config={},
            workspace=tmp_path,
            timeout=10,
            cancel_event=cancel,
            publish=forbidden,
            job_id="job-steps",
            inpaint_result={"method": "fixture"},
        )
    assert packaged == [True]


def test_surface_collider_failure_lists_each_object_and_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.orchestration.scene.object_geometry_steps import SurfaceInput, run_surface_colliders

    monkeypatch.setattr(
        pipeline,
        "_run",
        lambda *args, **kwargs: {
            "objects": [
                {
                    "id": "chair",
                    "parts": 0,
                    "error": "strict surface quality gate failed: intersection_budget_exceeded",
                },
                {"id": "table", "parts": 0, "error": "surface parts exceed budget"},
            ]
        },
    )
    inputs = [
        SurfaceInput(key, tmp_path / f"{key}.glb", "sha256:" + "a" * 64, tmp_path / f"{key}-collider.glb")
        for key in ("chair", "table")
    ]
    with pytest.raises(pipeline.ObjectifyError) as error:
        run_surface_colliders(tmp_path / "python", inputs, {}, tmp_path, 10, None)
    assert "chair: chưa hoàn tất kiểm tra giao cắt" in str(error.value)
    assert "table: số phần rời vượt giới hạn khối lồi của vật" in str(error.value)
    assert error.value.retryable is False


def test_repeated_collider_failures_keep_all_ids_in_the_public_error_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services.orchestration.scene.object_geometry_steps import SurfaceInput, run_surface_colliders

    keys = [f"candidate-{i:03d}" for i in range(6)]
    monkeypatch.setattr(
        pipeline,
        "_run",
        lambda *args, **kwargs: {
            "objects": [
                {
                    "id": key,
                    "parts": 0,
                    "error": "CoACD returned no parts or exceeded the part budget; hull fallback is forbidden",
                }
                for key in keys
            ]
        },
    )
    inputs = [
        SurfaceInput(key, tmp_path / f"{key}.glb", "sha256:" + "a" * 64, tmp_path / f"{key}-collider.glb")
        for key in keys
    ]
    with pytest.raises(pipeline.ObjectifyError) as error:
        run_surface_colliders(tmp_path / "python", inputs, {}, tmp_path, 10, None)
    assert len(str(error.value)) < 500
    assert all(key in str(error.value) for key in keys)
