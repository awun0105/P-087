"""Counterexamples audit: không xuyên tường, không tin receipt, đúng seed native."""

import json
import math
from pathlib import Path

import pytest

from src.models.contracts.reconstruction import CapsuleFootprint, SeedDecision
from src.services.reconstruction.adapters.voxel import SplatTransformVoxelAdapter, SyntheticVoxelRequest
from src.services.reconstruction.adapters.voxel_clearance import validate_seed_clearance
from src.services.reconstruction.adapters.voxel_runtime import VoxelRuntimeSettings
from src.services.reconstruction.rgb.geometry_publication import GeometryExecutionRequest, GeometryResolver
from src.services.reconstruction.rgb.voxel import native_from_world
from tests.test_reconstruction.support.rec05_occupancy_fixture import wall, write_occupancy
from tests.test_reconstruction.test_rec05_adapter import FixtureProcess, request
from tests.test_reconstruction.test_rec05_clearance import CUBE, world_of
from tests.test_reconstruction.test_rec05_product_pipeline import setup_pipeline
from tests.test_reconstruction.test_rec05_voxel import config


def test_narrow_corridor_cannot_escape_through_wall(tmp_path: Path) -> None:
    write_occupancy(tmp_path, wall(0, range(30, 31)) | wall(0, range(33, 34)))
    with pytest.raises(ValueError, match="within the relocation bound"):
        validate_seed_clearance(
            tmp_path, config(navigation_seed_world=world_of((31, 32, 32)), max_seed_relocation_m=0.3)
        )


def test_solid_center_has_no_implicit_side_of_wall(tmp_path: Path) -> None:
    write_occupancy(tmp_path, wall(0, range(30, 32)))
    with pytest.raises(ValueError, match="unambiguous free air"):
        validate_seed_clearance(tmp_path, config(navigation_seed_world=world_of((30, 32, 32))))


def test_distance_uses_requested_subvoxel_point(tmp_path: Path) -> None:
    write_occupancy(tmp_path, CUBE)
    settings = config(navigation_seed_world=(-0.08, -0.05, 0.05), max_seed_relocation_m=0.2)
    receipt = validate_seed_clearance(tmp_path, settings)
    distance = math.dist(receipt["requested_seed_world"], receipt["accepted_seed_world"])
    assert receipt["relocation_distance_m"] == distance <= 0.2


def test_carve_receives_accepted_seed(tmp_path: Path) -> None:
    class RelocationProcess(FixtureProcess):
        def run(self, arguments: tuple[str, ...], target: tuple[Path, str]) -> str:
            text = super().run(arguments, target)
            workspace, name = target
            if name == "occupancy":
                write_occupancy(workspace, CUBE)
            if name == "collision":
                receipt = json.loads((workspace / "seed-clearance.json").read_text())
                seed = arguments[arguments.index("--seed-pos") + 1]
                assert tuple(float(value) for value in seed.split(",")) == native_from_world(
                    receipt["accepted_seed_world"]
                )
                assert receipt["relocates"]
            return text

    source = tmp_path / "fixture.ply"
    source.write_bytes(b"fixture")
    task = request(source).model_dump() | {"config": config(navigation_seed_world=world_of((31, 32, 32)))}
    adapter = SplatTransformVoxelAdapter(
        RelocationProcess(VoxelRuntimeSettings(cli=Path("unused"), module_path=Path("unused")))
    )
    adapter.run_synthetic(SyntheticVoxelRequest.model_validate(task), tmp_path / "attempt")


def test_owner_robot_is_clearance_cylinder_not_physics_capsule() -> None:
    footprint = CapsuleFootprint(shape="clearance_cylinder", height_m=0.308, radius_m=0.461, length_m=0.308)
    assert footprint.height_m < 2 * footprint.radius_m
    with pytest.raises(ValueError):
        CapsuleFootprint(height_m=0.308, radius_m=0.461, length_m=0)


def test_contract_recomputes_seed_distance() -> None:
    with pytest.raises(ValueError, match="differs from the two seed points"):
        SeedDecision(
            requested_world_m=(0, 0, 0),
            accepted_world_m=(0.3, 0.3, 0.3),
            relocates=True,
            relocation_distance_m=0.3,
            relocation_bound_m=0.3,
            occupancy_checksum="sha256:" + "a" * 64,
            clearance_evidence_checksum="sha256:" + "b" * 64,
        )


def test_config_retry_namespace_and_portable_outputs(tmp_path: Path) -> None:
    service, canonicalizer, confirmation, metric, _ = setup_pipeline(tmp_path)
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=confirmation,
        source_visual=metric.source_visual,
        job_id="test-job-rec05",
        config=config(),
    )
    first = service.execute(req, tmp_path / "first")
    second = service.execute(
        req.model_copy(update={"config": config(capsule_height_m=0.308, capsule_radius_m=0.461)}), tmp_path / "second"
    )
    assert first.geometry_ref.artifact_uri != second.geometry_ref.artifact_uri
    resolver = GeometryResolver(canonicalizer.deps.visuals.resolve)
    assert resolver.require(second.voxel_binary_ref).is_file()
    manifest = json.loads(resolver.require(second.manifest_ref).read_text())
    assert manifest["geometry"]["capsule"]["shape"] == "clearance_cylinder"
    assert resolver.load(second.manifest_ref).geometry == second.geometry
    assert resolver.load_seed_clearance(second.clearance)["status"] == "VALID"
    decision = json.loads(resolver.require(second.clearance.seed_clearance).read_text())
    decision["accepted_seed_world"] = [1000, 1000, 1000]
    bad_ref = service.deps.publisher.publish_clearance("bad.json", json.dumps(decision).encode(), {})
    with pytest.raises(ValueError, match="replay"):
        resolver.load_seed_clearance(second.clearance.model_copy(update={"seed_clearance": bad_ref}))


def test_identical_config_new_attempt_does_not_overwrite(tmp_path: Path) -> None:
    service, _, confirmation, metric, _ = setup_pipeline(tmp_path)
    req = GeometryExecutionRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=confirmation,
        source_visual=metric.source_visual,
        job_id="test-job-rec05",
        config=config(),
    )
    first = service.execute(req, tmp_path / "attempt-one")
    second = service.execute(req, tmp_path / "attempt-two")
    assert first.geometry_ref.artifact_uri != second.geometry_ref.artifact_uri
    assert first.geometry_ref.artifact_checksum == second.geometry_ref.artifact_checksum
