"""Fixture-first EX-SCENE pipeline proof from bundle to editable SceneIR."""

import json
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ArtifactRef, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.identity import verify_content_checksum
from src.services.orchestration.artifacts import ArtifactResolver, sha256_bytes
from src.services.scene.association.baseline import associate_masks
from src.services.scene.bundle_consumer import load_reconstruction_bundle
from src.services.scene.candidates.builder import build_candidates
from src.services.scene.candidates.models import CandidateObject, CandidateState
from src.services.scene.candidates.operations import confirm_candidate, ignore_candidate, rename_candidate
from src.services.scene.decomposition.baseline import decompose_scene
from src.services.scene.editing.commands import (
    PrimitiveObjectCommand,
    add_primitive_object,
    move_object,
    set_object_active,
)
from src.services.scene.extraction.deterministic import extract_fixture_masks
from src.services.scene.publisher import build_scene_ir
from src.services.scene.worker import run_fixture_scene_worker

FIXTURES = Path(__file__).parents[2] / "fixtures"
STORE = FIXTURES / "artifact_store"


def _stage_bundle(tmp_path: Path, name: str = "manifest.json") -> tuple[ArtifactRef, ArtifactResolver]:
    payload = (FIXTURES / "reconstruction_bundle" / name).read_bytes().replace(b"\r\n", b"\n")
    document = json.loads(payload)
    resolver = ArtifactResolver(tmp_path)
    reference = ProductArtifactRef(
        artifact_type="ReconstructionBundle",
        schema_version="1.0",
        artifact_uri=document["artifact_uri"],
        artifact_checksum=sha256_bytes(payload),
        data_class="derived",
        producer_stage=document["producer_stage"],
        job_id=document["job_id"],
    )
    _write_artifacts(tmp_path, resolver, reference, payload)
    return reference, resolver


def _write_artifacts(tmp_path: Path, resolver: ArtifactResolver, reference: ArtifactRef, payload: bytes) -> None:
    target = resolver.resolve(reference.artifact_uri)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    for source in STORE.rglob("*"):
        if source.is_file():
            destination = tmp_path / source.relative_to(STORE)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))


def _scene_from_fixture(tmp_path: Path):
    reference, resolver = _stage_bundle(tmp_path)
    view = load_reconstruction_bundle(reference, resolver)
    mask_set = extract_fixture_masks(view)
    groups = associate_masks(mask_set, view)
    candidates = build_candidates(groups)
    confirmed = tuple(confirm_candidate(item, "tester")[0] for item in candidates)
    return build_scene_ir(decompose_scene(confirmed, view), view)


def test_fixture_extraction_association_and_candidate_state(tmp_path: Path) -> None:
    """Fixture masks become deterministic candidates without evaluation annotations."""
    reference, resolver = _stage_bundle(tmp_path)
    view = load_reconstruction_bundle(reference, resolver)
    mask_set = extract_fixture_masks(view)
    groups = associate_masks(mask_set, view)
    candidates = build_candidates(groups)

    assert mask_set.model_version == "real2sim.fixture-extractor.v1"
    assert groups[0].candidate_id == "candidate-fixture-object-001"
    assert candidates[0].state == CandidateState.UNREVIEWED
    assert candidates[0].geometry_ref == view.bundle.canonical_geometry_ref


def test_candidate_operations_are_auditable() -> None:
    """Confirmation operations keep stable identity and explicit audit metadata."""
    reference = ArtifactRef(
        artifact_type="ObjectGeometry",
        schema_version="1.0",
        artifact_uri="artifact://jobs/job-fixture-001/scene/object.ply",
        artifact_checksum="sha256:" + "1" * 64,
        data_class="derived",
        producer_stage="ST-SCENE-DECOMPOSE",
        job_id="job-fixture-001",
    )
    candidate = CandidateObject(
        candidate_id="candidate-001",
        name="Box",
        state=CandidateState.UNREVIEWED,
        mask_ids=("mask-001",),
        geometry_ref=reference,
        provenance={"fixture": True},
    )
    renamed, rename_event = rename_candidate(candidate, "Pallet", "tester")
    confirmed, confirm_event = confirm_candidate(renamed, "tester")

    assert confirmed.name == "Pallet"
    assert confirmed.state == CandidateState.CONFIRMED
    assert rename_event.operation == "rename"
    assert confirm_event.candidate_ids == ("candidate-001",)
    with pytest.raises(ValueError, match="ignored candidate"):
        confirm_candidate(ignore_candidate(candidate, "tester")[0], "tester")


def test_scene_worker_outputs_valid_scene_ir(tmp_path: Path) -> None:
    """Worker boundary creates checksummed SceneIR from a bundle ref."""
    reference, resolver = _stage_bundle(tmp_path)
    result = run_fixture_scene_worker(reference, resolver)

    assert result.status == "SUCCEEDED"
    assert result.scene_ir is not None
    assert result.scene_ir.objects[0].state == "CONFIRMED"
    verify_content_checksum(result.scene_ir, "scene_ir_checksum")


def test_scene_edit_move_delete_and_add_primitive(tmp_path: Path) -> None:
    """Edit operations refresh SceneIR identity and preserve canonical transforms."""
    scene = _scene_from_fixture(tmp_path)
    transform = Transform(
        parent_frame="world",
        local_frame=scene.objects[0].local_frame,
        translation_xyz=(1.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
    moved = move_object(scene, scene.objects[0].id, transform)
    deleted = set_object_active(moved, scene.objects[0].id, False)
    command = PrimitiveObjectCommand(
        object_id="object-user-box-001",
        name="User Box",
        transform=Transform(
            parent_frame="world",
            local_frame="object-user-box-001",
            translation_xyz=(2.0, 0.0, 0.0),
            rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
        geometry_ref=scene.environment.geometry_ref,
        dimensions_xyz_m=(0.5, 0.5, 0.5),
    )
    added = add_primitive_object(deleted, command)

    assert moved.scene_ir_checksum != scene.scene_ir_checksum
    assert deleted.objects[0].active is False
    assert added.objects[-1].origin == "user_added"
    assert added.objects[-1].primitive_dimensions_xyz_m == (0.5, 0.5, 0.5)
    verify_content_checksum(added, "scene_ir_checksum")


def test_invalid_scene_edit_is_rejected(tmp_path: Path) -> None:
    """Transforms cannot target a different local frame."""
    scene = _scene_from_fixture(tmp_path)
    transform = Transform(
        parent_frame="world",
        local_frame="wrong-frame",
        translation_xyz=(0.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
    with pytest.raises(ValueError, match="local_frame"):
        move_object(scene, scene.objects[0].id, transform)
