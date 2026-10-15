"""Region box resolution: acceptance tests for T-004 (one test per criterion in the plan)."""

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import ObjectMembershipArtifact, ObjectRegionCommand, RegionBox
from src.services.scene.editing.membership import ObjectMembershipValidationError
from src.services.scene.editing.region_box import apply_resolution, boxes_contain, preview_payload, resolve_region


def box(**changes: object) -> dict:
    return {"op": "add", "center_m": [0.0, 0.0, 0.5], "half_extents_m": [0.3, 0.3, 0.5], "yaw_rad": 0.0} | changes


@pytest.mark.parametrize("half", [0.005, 20.0])
def test_criterion_0_closed_half_extent_bounds_are_accepted(half: float) -> None:
    RegionBox.model_validate(box(half_extents_m=[half, half, half]))


@pytest.mark.parametrize("half", [0.0049, 20.0001])
def test_criterion_0_just_outside_half_extent_bounds_are_rejected(half: float) -> None:
    with pytest.raises(ValidationError):
        RegionBox.model_validate(box(half_extents_m=[half, half, half]))


def region(op: str = "add", center=(0.0, 0.0, 0.0), half=(1.0, 1.0, 1.0), yaw: float = 0.0) -> RegionBox:
    return RegionBox(op=op, center_m=center, half_extents_m=half, yaw_rad=yaw)


def test_axis_aligned_box_contains_its_interior_only() -> None:
    points = np.array([[0.0, 0.0, 0.0], [0.9, -0.9, 0.9], [1.1, 0.0, 0.0], [0.0, 0.0, -1.1]])
    assert boxes_contain(points, [region()]).tolist() == [True, True, False, False]


def test_box_rotated_45_degrees_follows_its_own_axes() -> None:
    along_x = [0.9 * math.cos(math.pi / 4), 0.9 * math.sin(math.pi / 4), 0.0]
    points = np.array([along_x, [0.8, 0.0, 0.0], [0.0, 0.9, 0.0], [0.0, 0.0, 0.9], [0.0, 0.0, 1.05]])
    inside = boxes_contain(points, [region(half=(1.0, 0.2, 1.0), yaw=math.pi / 4)])
    assert inside.tolist() == [True, False, False, True, False]


def test_subtract_box_carves_a_hole_out_of_the_add_box() -> None:
    points = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [-1.9, 0.0, 0.0], [2.5, 0.0, 0.0]])
    boxes = [region(half=(2.0, 2.0, 2.0)), region("subtract", half=(0.5, 0.5, 2.0))]
    assert boxes_contain(points, boxes).tolist() == [False, True, True, False]


def test_points_on_a_face_are_inside_and_two_micrometres_outside_are_not() -> None:
    on_face = np.array([[1.0, 0.2, 0.3], [-1.0, 0.0, -1.0], [1.0 + 0.5e-6, 0.0, 0.0]])
    just_outside = np.array([[1.0 + 2e-6, 0.0, 0.0], [0.0, 1.0 + 2e-6, 0.0], [0.0, 0.0, -1.0 - 2e-6]])
    assert boxes_contain(on_face, [region()]).tolist() == [True, True, True]
    assert boxes_contain(just_outside, [region()]).tolist() == [False, False, False]


def test_non_finite_points_are_never_inside() -> None:
    points = np.array([[np.nan, 0.0, 0.0], [0.0, np.inf, 0.0]])
    assert boxes_contain(points, [region()]).tolist() == [False, False]


def test_subtract_without_any_add_box_contains_nothing() -> None:
    assert not boxes_contain(np.zeros((3, 3)), [region("subtract")]).any()


JOB = "job-region"
CHECKSUM = "sha256:" + "b" * 64
IDENTITY = Transform(
    parent_frame="world",
    local_frame="a",
    translation_xyz=(0.0, 0.0, 0.0),
    rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
)


def _ref(artifact_type: str, payload: bytes, suffix: str) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB}/scene/region/{suffix}",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.SCENE_DECOMPOSE,
        job_id=JOB,
    )


def manifest_for(gaussian_count: int) -> ObjectMembershipArtifact:
    return ObjectMembershipArtifact(
        source_visual_ref=_ref("GaussianPLY", b"visual", "visual.ply"),
        source_geometry_ref=_ref("GeometryPLY", b"geometry", "geometry.ply"),
        extraction_revision="rev-001",
        coordinate_system=CoordinateSystem(),
        gaussian_count=gaussian_count,
        labels_ref=_ref("ObjectMembershipLabels", b"labels", "labels.i32le"),
        label_to_object_id={"1": "a", "2": "b"},
    )


def synthetic_scene() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sàn z=0; vật a (nhãn 1) và b (nhãn 2) cạnh nhau; dải nền giữa hai vật; nền rải rác xa."""
    floor = np.array([(x, y, 0.0) for x in np.arange(-1.0, 3.01, 0.25) for y in np.arange(-1.0, 2.01, 0.25)])
    a = np.array(
        [
            (x, y, z)
            for x in np.linspace(0.0, 1.0, 11)
            for y in np.linspace(0.0, 1.0, 11)
            for z in np.linspace(0.1, 1.0, 10)
        ]
    )
    b = np.array(
        [
            (x, y, z)
            for x in np.linspace(1.2, 2.2, 11)
            for y in np.linspace(0.0, 1.0, 11)
            for z in np.linspace(0.1, 1.0, 10)
        ]
    )
    gap = np.array(
        [(x, y, z) for x in (1.05, 1.10, 1.15) for y in np.linspace(0.0, 1.0, 11) for z in np.linspace(0.1, 1.0, 10)]
    )
    far = np.random.default_rng(7).uniform([-2.5, -2.0, 0.2], [-1.5, 2.0, 1.5], size=(40, 3))
    positions = np.vstack([floor, a, b, gap, far])
    role = np.concatenate(
        [["floor"] * len(floor), ["a"] * len(a), ["b"] * len(b), ["gap"] * len(gap), ["far"] * len(far)]
    )
    labels = np.select([role == "a", role == "b"], [1, 2], default=-1).astype(np.int32)
    return positions, labels, role == "floor", role


POSITIONS, LABELS, FLOOR, ROLE = synthetic_scene()
MANIFEST = manifest_for(len(POSITIONS))


def add_box(center, half, yaw: float = 0.0) -> RegionBox:
    return RegionBox(op="add", center_m=center, half_extents_m=half, yaw_rad=yaw)


def sub_box(center, half, yaw: float = 0.0) -> RegionBox:
    return RegionBox(op="subtract", center_m=center, half_extents_m=half, yaw_rad=yaw)


def in_axis_box(points: np.ndarray, center, half) -> np.ndarray:
    return np.all(np.abs(points - np.asarray(center)) <= np.asarray(half) + 1e-6, axis=1)


def command(*boxes: RegionBox, claim_from: tuple[str, ...] = ()) -> ObjectRegionCommand:
    return ObjectRegionCommand(
        expected_scene_revision="rev-007", membership_checksum=CHECKSUM, boxes=list(boxes), claim_from=list(claim_from)
    )


def resolve_scene(
    *boxes: RegionBox,
    object_id: str = "a",
    claim_from: tuple[str, ...] = (),
    source=IDENTITY,
    positions=POSITIONS,
    manifest=MANIFEST,
):
    return resolve_region(
        positions_world=positions,
        labels=LABELS,
        manifest=manifest,
        object_id=object_id,
        source_world_from_object=source,
        command=command(*boxes, claim_from=claim_from),
        floor_protected=FLOOR,
    )


def test_criterion_1_box_covering_a_adds_and_removes_nothing() -> None:
    res = resolve_scene(add_box((0.5, 0.5, 0.55), (0.52, 0.52, 0.5)))
    assert res.added.size == 0 and res.removed.size == 0
    assert set(np.flatnonzero(res.object_mask)) == set(np.flatnonzero(ROLE == "a"))


def test_criterion_2_shrunk_box_returns_the_lower_half_to_background() -> None:
    res = resolve_scene(add_box((0.5, 0.5, 0.875), (0.52, 0.52, 0.325)))
    expected = np.flatnonzero((ROLE == "a") & (POSITIONS[:, 2] < 0.55))
    assert len(expected) == 605
    assert set(res.removed) == set(expected)
    assert res.added.size == 0


def test_criterion_3_box_bulging_into_background_adds_non_floor_rows() -> None:
    res = resolve_scene(add_box((0.5, 0.5, 0.55), (0.9, 0.52, 0.52)))
    assert set(res.added) == set(np.flatnonzero(ROLE == "gap"))
    assert not np.any(FLOOR[res.added])


def test_criterion_4_floor_rows_inside_the_box_are_never_added_and_are_counted() -> None:
    res = resolve_scene(add_box((0.5, 0.5, 0.55), (1.0, 1.0, 0.6)))
    inside_floor = (ROLE == "floor") & in_axis_box(POSITIONS, (0.5, 0.5, 0.55), (1.0, 1.0, 0.6))
    assert int(inside_floor.sum()) == 81
    assert res.protected_floor_count == 81
    assert not np.any(FLOOR[res.added])


def test_criterion_5_overlapping_object_stays_when_not_claimed() -> None:
    res = resolve_scene(add_box((1.0, 0.5, 0.55), (1.0, 0.52, 0.52)))
    assert res.overlaps == {"b": 990}
    assert res.claimed == {}
    assert not np.any(ROLE[res.added] == "b")


def test_criterion_6_claiming_b_moves_its_rows_inside_the_box() -> None:
    box = add_box((1.0, 0.5, 0.55), (1.0, 0.52, 0.52))
    res = resolve_scene(box, claim_from=("b",))
    inside_b = (ROLE == "b") & in_axis_box(POSITIONS, (1.0, 0.5, 0.55), (1.0, 0.52, 0.52))
    assert res.claimed == {"b": 990}
    assert res.overlaps == {}
    assert set(res.added[ROLE[res.added] == "b"]) == set(np.flatnonzero(inside_b))


def test_criterion_7_subtract_box_carves_the_middle_of_a() -> None:
    res = resolve_scene(add_box((0.5, 0.5, 0.55), (0.52, 0.52, 0.5)), sub_box((0.5, 0.5, 0.55), (0.2, 0.2, 0.2)))
    expected = np.flatnonzero((ROLE == "a") & in_axis_box(POSITIONS, (0.5, 0.5, 0.55), (0.2, 0.2, 0.2)))
    assert len(expected) == 100
    assert set(res.removed) == set(expected)
    assert int(res.object_mask.sum()) == int((ROLE == "a").sum()) - 100


def test_criterion_8_moved_object_is_resolved_from_its_source_pose_only() -> None:
    quarter_turn = Transform(
        parent_frame="world",
        local_frame="a",
        translation_xyz=(10.0, 0.0, 0.0),
        rotation_quaternion_xyzw=(0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)),
    )
    rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    world = POSITIONS @ rotation.T + np.array([10.0, 0.0, 0.0])
    box = add_box((0.5, 0.5, 0.55), (0.52, 0.52, 0.5))
    local = resolve_scene(box)
    from_source = resolve_scene(box, source=quarter_turn, positions=world)
    assert np.array_equal(from_source.object_mask, local.object_mask)
    assert np.array_equal(from_source.added, local.added)
    assert np.array_equal(from_source.removed, local.removed)
    with pytest.raises(ObjectMembershipValidationError):
        resolve_scene(box, source=IDENTITY, positions=world)


def test_criterion_9_object_below_fifty_rows_is_refused_with_a_delete_hint() -> None:
    with pytest.raises(ObjectMembershipValidationError, match="Xoá vật"):
        resolve_scene(add_box((0.0, 0.0, 0.1), (0.05, 0.05, 0.05)))


def test_criterion_10_only_the_matching_manifest_and_known_objects_are_accepted() -> None:
    box = add_box((0.5, 0.5, 0.55), (0.52, 0.52, 0.5))
    with pytest.raises(ObjectMembershipValidationError):
        resolve_scene(box, manifest=MANIFEST.model_copy(update={"gaussian_count": len(POSITIONS) - 1}))
    with pytest.raises(ObjectMembershipValidationError):
        resolve_scene(box, object_id="missing")
    with pytest.raises(ObjectMembershipValidationError):
        resolve_scene(box, claim_from=("missing",))


def test_object_cannot_claim_its_own_rows() -> None:
    with pytest.raises(ObjectMembershipValidationError, match="chính vật"):
        resolve_scene(add_box((0.5, 0.5, 0.55), (0.52, 0.52, 0.5)), claim_from=("a",))


def test_criterion_12_three_hundred_thousand_rows_resolve_within_the_budget() -> None:
    rng = np.random.default_rng(11)
    count = 300_000
    positions = rng.uniform([-2.0, -2.0, 0.0], [4.0, 3.0, 2.0], size=(count, 3))
    labels = rng.choice(np.array([-1, 1, 2], dtype=np.int32), size=count)
    boxes = [
        add_box((1.0, 0.5, 1.0), (1.5, 1.5, 1.2)),
        add_box((2.5, 1.0, 1.0), (0.8, 0.8, 0.8), yaw=0.3),
        sub_box((1.0, 0.5, 1.0), (0.3, 0.3, 0.3)),
        sub_box((2.5, 1.0, 1.0), (0.2, 0.2, 0.2), yaw=0.3),
    ]
    started = time.perf_counter()
    res = resolve_region(
        positions_world=positions,
        labels=labels,
        manifest=manifest_for(count),
        object_id="a",
        source_world_from_object=IDENTITY,
        command=command(*boxes),
        floor_protected=None,
    )
    elapsed = time.perf_counter() - started
    assert int(res.object_mask.sum()) >= 50
    assert elapsed < 0.3


def test_criterion_11_apply_relabels_rows_and_never_touches_the_input() -> None:
    res = resolve_scene(add_box((0.5, 0.5, 0.875), (0.52, 0.52, 0.325)))
    before = LABELS.copy()
    updated = apply_resolution(LABELS, MANIFEST, "a", res)
    assert np.array_equal(LABELS, before)
    assert set(updated[res.removed]) == {-1}
    untouched = np.ones(len(LABELS), dtype=bool)
    untouched[res.added] = False
    untouched[res.removed] = False
    assert np.array_equal(updated[untouched], LABELS[untouched])


def test_apply_gives_added_rows_the_object_label() -> None:
    res = resolve_scene(add_box((1.0, 0.5, 0.55), (1.0, 0.52, 0.52)), claim_from=("b",))
    updated = apply_resolution(LABELS, MANIFEST, "a", res)
    assert set(updated[res.added]) == {1}
    assert np.count_nonzero(updated == 1) == np.count_nonzero(LABELS == 1) + len(res.added)


def test_preview_payload_reports_counts_and_deterministic_samples() -> None:
    res = resolve_scene(add_box((1.0, 0.5, 0.55), (1.0, 0.52, 0.52)), claim_from=("b",))
    payload = preview_payload(res, POSITIONS, sample_limit=50)
    assert payload["added_count"] == len(res.added) == 330 + 990
    assert payload["removed_count"] == 0
    assert payload["object_gaussian_count"] == int(res.object_mask.sum())
    assert payload["claimed"] == {"b": 990}
    assert payload["overlaps"] == {}
    assert payload["protected_floor_count"] == 0
    assert len(payload["added_sample_m"]) == 50
    assert payload["removed_sample_m"] == []
    assert payload == preview_payload(res, POSITIONS, sample_limit=50)


def test_preview_samples_are_complete_below_the_limit() -> None:
    res = resolve_scene(add_box((1.0, 0.5, 0.55), (1.0, 0.52, 0.52)), claim_from=("b",))
    payload = preview_payload(res, POSITIONS)
    assert len(payload["added_sample_m"]) == len(res.added)
    assert payload["added_sample_m"][0] == POSITIONS[res.added[0]].tolist()


#: Ca kiểm chung với client: cùng file được vitest đọc (frontend/tests/region-box-model.test.ts).
SHARED_CASES = json.loads((Path(__file__).parents[2] / "tests/fixtures/region_box_cases.json").read_text("utf-8"))[
    "cases"
]


def test_shared_case_file_has_at_least_eight_cases() -> None:
    assert len(SHARED_CASES) >= 8


@pytest.mark.parametrize("case", SHARED_CASES, ids=[case["id"] for case in SHARED_CASES])
def test_shared_case_matches_the_frontend_contains_contract(case: dict) -> None:
    region = RegionBox.model_validate(case["box"])
    inside = boxes_contain(np.array([case["point_m"]], dtype=float), [region])
    assert bool(inside[0]) is case["inside"]
