"""Model ground truth của benchmark: biên giá trị, id trùng, độ dài danh sách (architecture §15.2)."""

import pytest
from pydantic import ValidationError

from src.services.orchestration.value.ground_truth import (
    BenchmarkTruth,
    GapCheck,
    L4Declaration,
    MeasuredDistance,
    RobotProfile,
)


def _robot(**overrides: float) -> dict:
    body = {"width_m": 0.5, "safety_margin_m": 0.1, "height_min_m": 0.05, "height_max_m": 1.2}
    body.update(overrides)
    return body


def _distance(identifier: str = "d1", **overrides: object) -> dict:
    body = {"id": identifier, "label": "bàn", "a": (0.0, 0.0, 0.0), "b": (1.0, 0.0, 0.0), "real_m": 1.0}
    body.update(overrides)
    return body


def _gap(identifier: str = "g1", span: float = 0.5, **overrides: object) -> dict:
    body = {
        "id": identifier,
        "label": "khe cửa",
        "layout": "A",
        "a": (0.0, 0.0, 0.0),
        "b": (span, 0.0, 0.0),
        "real_passable": True,
    }
    body.update(overrides)
    return body


def test_defaults_form_a_valid_empty_truth() -> None:
    truth = BenchmarkTruth()

    assert truth.include_in_benchmark is False
    assert truth.distances == [] and truth.gaps == [] and truth.layouts == {}


def test_robot_height_range_must_be_increasing() -> None:
    with pytest.raises(ValidationError, match="height_min_m phải nhỏ hơn height_max_m"):
        RobotProfile(**_robot(height_min_m=1.0, height_max_m=1.0))
    assert RobotProfile(**_robot(height_min_m=0.9, height_max_m=1.0)).height_max_m == 1.0


@pytest.mark.parametrize("width", [0.05, 3.01])
def test_robot_width_bounds_are_exclusive_below_and_inclusive_above(width: float) -> None:
    with pytest.raises(ValidationError):
        RobotProfile(**_robot(width_m=width))
    assert RobotProfile(**_robot(width_m=3.0)).width_m == 3.0


@pytest.mark.parametrize("span", [0.1, 10.0])
def test_gap_span_accepts_both_ends_of_the_range(span: float) -> None:
    assert GapCheck(**_gap(span=span)).id == "g1"


@pytest.mark.parametrize("span", [0.099, 10.01])
def test_gap_span_outside_the_range_is_rejected(span: float) -> None:
    with pytest.raises(ValidationError, match="nằm ngoài khoảng"):
        GapCheck(**_gap(span=span))


def test_distance_points_must_differ() -> None:
    with pytest.raises(ValidationError, match="trùng nhau"):
        MeasuredDistance(**_distance(b=(0.0, 0.0, 0.0)))


def test_ids_must_be_unique_across_distances_and_gaps() -> None:
    with pytest.raises(ValidationError, match="id trùng trong distances/gaps: x1"):
        BenchmarkTruth(distances=[_distance("x1")], gaps=[_gap("x1")])


def test_key_obstacle_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="key_obstacle_ids có id trùng"):
        BenchmarkTruth(key_obstacle_ids=["chair", "chair"])


def test_list_length_limits_are_enforced() -> None:
    with pytest.raises(ValidationError):
        BenchmarkTruth(distances=[_distance(f"d{index}") for index in range(33)])
    with pytest.raises(ValidationError):
        BenchmarkTruth(key_obstacle_ids=[f"o{index}" for index in range(65)])


def test_evidence_length_is_between_one_and_600() -> None:
    with pytest.raises(ValidationError):
        L4Declaration(layout_a_passed=True, layout_b_passed=True, matches_reality=True, evidence="")
    with pytest.raises(ValidationError):
        L4Declaration(layout_a_passed=True, layout_b_passed=True, matches_reality=True, evidence="x" * 601)


def test_unknown_fields_are_rejected_at_every_level() -> None:
    with pytest.raises(ValidationError):
        BenchmarkTruth(surprise=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BenchmarkTruth(distances=[_distance(extra_field=1)])
