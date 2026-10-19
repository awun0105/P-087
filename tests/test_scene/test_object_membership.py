from __future__ import annotations

import hashlib

import numpy as np
import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import (
    ObjectMembershipArtifact,
    ObjectMembershipMergeCommand,
    ObjectMembershipReassignCommand,
    SourceGaussianROI,
)
from src.models.contracts.scene import SceneIR, SceneObjectState, SourceCollisionRegion
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.projects.registry import DEFAULT_FIXTURE_ROOT
from src.services.orchestration.scene.editor import SceneEditor
from src.services.scene.decomposition.gaussian_split import SplitConfig, split
from src.services.scene.editing.membership import (
    ObjectMembershipValidationError,
    StaleObjectMembershipRevisionError,
    decode_gaussian_membership_labels,
    encode_gaussian_membership_labels,
    membership_labels_for_parts,
    validate_object_membership_command,
)


def _fixture_scene() -> SceneIR:
    return SceneIR.model_validate_json((DEFAULT_FIXTURE_ROOT / "scene_ir" / "scene.json").read_bytes())


def _reference(
    source: ProductArtifactRef,
    artifact_type: str,
    payload: bytes,
    *,
    suffix: str,
    job_id: str | None = None,
) -> ProductArtifactRef:
    owner = job_id or source.job_id
    digest = hashlib.sha256(payload).hexdigest()
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{owner}/scene/membership/{suffix}",
        artifact_checksum=f"sha256:{digest}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.SCENE_DECOMPOSE,
        job_id=owner,
    )


def _membership(
    scene: SceneIR,
    *,
    labels: dict[str, str] | None = None,
    gaussian_count: int = 4,
    source_visual_ref: ProductArtifactRef | None = None,
    source_geometry_ref: ProductArtifactRef | None = None,
    label_bytes: bytes = b"labels",
) -> ObjectMembershipArtifact:
    visual_ref = source_visual_ref or _reference(
        scene.environment.geometry_ref, "MetricGaussianPly", b"source", suffix="source.ply"
    )
    return ObjectMembershipArtifact(
        source_visual_ref=visual_ref,
        source_geometry_ref=source_geometry_ref or scene.environment.geometry_ref,
        extraction_revision="rev-001",
        coordinate_system=CoordinateSystem(),
        gaussian_count=gaussian_count,
        labels_ref=_reference(
            scene.environment.geometry_ref,
            "ObjectMembershipLabels",
            label_bytes,
            suffix="labels.i32le",
        ),
        label_to_object_id=labels or {"0": "candidate-001"},
    )


def _candidate_scene(
    *,
    state: SceneObjectState = SceneObjectState.CANDIDATE,
    moved: bool = False,
    asset_backed: bool = False,
    extraction_revision: str = "rev-001",
    membership: ObjectMembershipArtifact | None = None,
) -> tuple[SceneIR, ObjectMembershipArtifact]:
    scene = _fixture_scene()
    geometry_ref = scene.environment.geometry_ref
    source_visual_ref = _reference(geometry_ref, "MetricGaussianPly", b"source", suffix="source.ply")
    selected = scene.objects[0]
    transform = selected.transform
    if moved:
        transform = transform.model_copy(update={"translation_xyz": (9.0, 8.0, 7.0)})
    ownership = SourceCollisionRegion(
        object_id=selected.id,
        source_geometry_ref=geometry_ref,
        extraction_revision=extraction_revision,
        source_transform=selected.transform,
        region_kind="source_obb",
        source_obb_dimensions_xyz_m=(1.0, 1.0, 1.0),
    )
    candidate = selected.model_copy(
        update={
            "state": state,
            "transform": transform,
            "primitive_dimensions_xyz_m": (1.0, 1.0, 1.0),
            "source_collision": ownership,
            "asset_ref": source_visual_ref if asset_backed else None,
        }
    )
    manifest = membership or _membership(
        scene,
        labels={"0": candidate.id},
        source_visual_ref=source_visual_ref,
        source_geometry_ref=geometry_ref,
    )
    background_master_ref = _reference(geometry_ref, "GaussianPLY", b"background", suffix="background.ply")
    environment = scene.environment.model_copy(
        update={"visual_master_ref": background_master_ref, "membership": manifest}
    )
    updated = scene.model_copy(update={"environment": environment, "objects": [candidate]})
    return with_canonical_checksum(updated, "scene_ir_checksum"), manifest


def _reassign(scene: SceneIR, manifest: ObjectMembershipArtifact) -> ObjectMembershipReassignCommand:
    return ObjectMembershipReassignCommand(
        expected_scene_revision=scene.scene_revision,
        membership_checksum=manifest.labels_ref.artifact_checksum,
        region=SourceGaussianROI(min_xyz_m=(0, 0, 0), max_xyz_m=(1, 1, 1)),
        source_object_id=next(iter(manifest.label_to_object_id.values())),
        target_object_id=None,
    )


def test_split_fallback_rows_are_persisted_as_background() -> None:
    rows = np.zeros(5, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4")])
    rows["x"] = np.arange(5, dtype=np.float32)
    source_labels = np.array([0, 0, 0, 1, 1], dtype=np.int32)

    background, parts = split(rows, source_labels, SplitConfig(min_object_gaussians=3))
    final_labels = membership_labels_for_parts(source_labels, [part.index for part in parts])

    assert len(background) == 2
    assert [part.index for part in parts] == [0]
    assert final_labels.tolist() == [0, 0, 0, -1, -1]
    with pytest.raises(ObjectMembershipValidationError, match="int32 range"):
        membership_labels_for_parts(source_labels, [2**32])


def test_label_bytes_round_trip_preserves_background_and_row_count() -> None:
    labels = np.array([0, 1, -1, 1], dtype=np.int32)
    mapping = {"0": "candidate-001", "1": "candidate-002"}
    payload = encode_gaussian_membership_labels(labels, gaussian_count=4, label_to_object_id=mapping)
    scene = _fixture_scene()
    manifest = _membership(scene, labels=mapping, gaussian_count=4, label_bytes=payload)

    assert len(payload) == 4 * np.dtype("<i4").itemsize
    assert decode_gaussian_membership_labels(payload, manifest).tolist() == [0, 1, -1, 1]


def test_encoder_rejects_count_unknown_label_and_int32_overflow() -> None:
    mapping = {"0": "candidate-001"}
    with pytest.raises(ObjectMembershipValidationError, match="one integer per source"):
        encode_gaussian_membership_labels(np.array([0]), gaussian_count=2, label_to_object_id=mapping)
    with pytest.raises(ObjectMembershipValidationError, match="unmapped object owner"):
        encode_gaussian_membership_labels(np.array([2]), gaussian_count=1, label_to_object_id=mapping)
    with pytest.raises(ObjectMembershipValidationError, match="int32 range"):
        encode_gaussian_membership_labels(
            np.array([2**32], dtype=np.uint64), gaussian_count=1, label_to_object_id={str(2**32): "candidate-001"}
        )


def test_decoder_rejects_changed_bytes_even_when_length_matches() -> None:
    scene = _fixture_scene()
    payload = encode_gaussian_membership_labels(
        np.array([0, -1, -1, -1], dtype=np.int32),
        gaussian_count=4,
        label_to_object_id={"0": "candidate-001"},
    )
    manifest = _membership(scene, label_bytes=payload)

    with pytest.raises(ObjectMembershipValidationError, match="checksum"):
        decode_gaussian_membership_labels(payload[:-4] + b"\x01\x00\x00\x00", manifest)
    wrong_count = ObjectMembershipArtifact.model_validate({**manifest.model_dump(mode="python"), "gaussian_count": 5})
    with pytest.raises(ObjectMembershipValidationError, match="byte count"):
        decode_gaussian_membership_labels(payload, wrong_count)


def test_membership_contract_allows_merge_mapping_and_rejects_cross_job_refs() -> None:
    scene = _fixture_scene()
    with pytest.raises(ValidationError, match="gaussian_count"):
        _membership(scene, gaussian_count=True)
    merged_mapping = {"0": "candidate-001", "1": "candidate-001"}
    merged_payload = encode_gaussian_membership_labels(
        np.array([0, 1, -1], dtype=np.int32),
        gaussian_count=3,
        label_to_object_id=merged_mapping,
    )
    merged = _membership(scene, labels=merged_mapping, gaussian_count=3, label_bytes=merged_payload)
    assert decode_gaussian_membership_labels(merged_payload, merged).tolist() == [0, 1, -1]

    base = _membership(scene)
    foreign_visual = _reference(
        scene.environment.geometry_ref,
        "MetricGaussianPly",
        b"source",
        suffix="source.ply",
        job_id="another-job",
    )
    with pytest.raises(ValidationError, match="same job"):
        ObjectMembershipArtifact.model_validate({**base.model_dump(mode="python"), "source_visual_ref": foreign_visual})


def test_roi_rejects_nan_and_merge_rejects_duplicate_or_self_ids() -> None:
    with pytest.raises(ValidationError):
        SourceGaussianROI(min_xyz_m=(0, 0, float("nan")), max_xyz_m=(1, 1, 1))
    with pytest.raises(ValidationError, match="unique"):
        ObjectMembershipMergeCommand(
            expected_scene_revision="rev-001",
            membership_checksum="sha256:" + "0" * 64,
            primary_object_id="candidate-001",
            secondary_object_ids=["candidate-002", "candidate-002"],
        )
    with pytest.raises(ValidationError, match="cannot also be secondary"):
        ObjectMembershipMergeCommand(
            expected_scene_revision="rev-001",
            membership_checksum="sha256:" + "0" * 64,
            primary_object_id="candidate-001",
            secondary_object_ids=["candidate-001"],
        )
    with pytest.raises(ValidationError, match="must differ"):
        ObjectMembershipReassignCommand(
            expected_scene_revision="rev-001",
            membership_checksum="sha256:" + "0" * 64,
            region=SourceGaussianROI(min_xyz_m=(0, 0, 0), max_xyz_m=(1, 1, 1)),
            source_object_id="candidate-001",
            target_object_id="candidate-001",
        )


def test_valid_reassign_requires_current_revision_checksum_and_source_ownership() -> None:
    scene, manifest = _candidate_scene()
    command = _reassign(scene, manifest)

    assert validate_object_membership_command(scene, command) == manifest
    with pytest.raises(StaleObjectMembershipRevisionError, match="current SceneIR"):
        validate_object_membership_command(scene, command.model_copy(update={"expected_scene_revision": "rev-000"}))
    with pytest.raises(ObjectMembershipValidationError, match="checksum"):
        validate_object_membership_command(
            scene, command.model_copy(update={"membership_checksum": "sha256:" + "0" * 64})
        )


@pytest.mark.parametrize(
    ("state", "moved", "asset_backed", "extraction_revision"),
    [
        (SceneObjectState.CONFIRMED, False, False, "rev-001"),
        (SceneObjectState.CANDIDATE, True, False, "rev-001"),
        (SceneObjectState.CANDIDATE, False, True, "rev-001"),
        (SceneObjectState.CANDIDATE, False, False, "rev-000"),
    ],
)
def test_correction_rejects_confirmed_moved_asset_or_stale_source_candidate(
    state: SceneObjectState,
    moved: bool,
    asset_backed: bool,
    extraction_revision: str,
) -> None:
    scene, manifest = _candidate_scene(
        state=state,
        moved=moved,
        asset_backed=asset_backed,
        extraction_revision=extraction_revision,
    )

    with pytest.raises(ObjectMembershipValidationError, match="confirmed, moved, asset-backed"):
        validate_object_membership_command(scene, _reassign(scene, manifest))


def test_correction_rejects_legacy_scene_and_membership_missing_source_visual() -> None:
    legacy = _fixture_scene()
    command = ObjectMembershipReassignCommand(
        expected_scene_revision=legacy.scene_revision,
        membership_checksum="sha256:" + "0" * 64,
        region=SourceGaussianROI(min_xyz_m=(0, 0, 0), max_xyz_m=(1, 1, 1)),
        source_object_id=None,
        target_object_id="candidate-001",
    )
    assert legacy.environment.membership is None
    assert "membership" not in legacy.environment.model_dump(mode="json", exclude_none=True)
    assert legacy.scene_ir_checksum == with_canonical_checksum(legacy, "scene_ir_checksum").scene_ir_checksum
    with pytest.raises(ObjectMembershipValidationError, match="no persisted Gaussian membership"):
        validate_object_membership_command(legacy, command)

    scene = _fixture_scene()
    manifest = _membership(scene)
    with pytest.raises(ValidationError, match="source_visual_ref"):
        ObjectMembershipArtifact.model_validate({**manifest.model_dump(mode="python"), "source_visual_ref": None})


def test_correction_rejects_mismatched_geometry_and_missing_mapped_object() -> None:
    scene, manifest = _candidate_scene()
    mismatched_geometry = _reference(
        scene.environment.geometry_ref,
        "EnvironmentGeometry",
        b"different geometry",
        suffix="different.glb",
    )
    bad_geometry_manifest = ObjectMembershipArtifact.model_validate(
        {**manifest.model_dump(mode="python"), "source_geometry_ref": mismatched_geometry}
    )
    bad_geometry_environment = scene.environment.model_copy(update={"membership": bad_geometry_manifest})
    bad_geometry_scene = scene.model_copy(update={"environment": bad_geometry_environment})
    with pytest.raises(ObjectMembershipValidationError, match="source geometry"):
        validate_object_membership_command(bad_geometry_scene, _reassign(bad_geometry_scene, bad_geometry_manifest))

    missing_object_manifest = ObjectMembershipArtifact.model_validate(
        {**manifest.model_dump(mode="python"), "label_to_object_id": {"0": "missing-candidate"}}
    )
    missing_object_environment = scene.environment.model_copy(update={"membership": missing_object_manifest})
    missing_object_scene = scene.model_copy(update={"environment": missing_object_environment})
    with pytest.raises(ObjectMembershipValidationError, match="objects missing"):
        validate_object_membership_command(
            missing_object_scene, _reassign(missing_object_scene, missing_object_manifest)
        )


def test_scene_artifact_allowlist_includes_membership_refs_without_duplicate_geometry() -> None:
    scene, manifest = _candidate_scene()
    references = SceneEditor.artifact_references(scene)
    uris = [reference.artifact_uri for reference in references]

    assert manifest.labels_ref.artifact_uri in uris
    assert manifest.source_visual_ref.artifact_uri in uris
    assert scene.environment.visual_master_ref is not None
    assert scene.environment.visual_master_ref.artifact_uri in uris
    assert uris.count(scene.environment.geometry_ref.artifact_uri) == 1
