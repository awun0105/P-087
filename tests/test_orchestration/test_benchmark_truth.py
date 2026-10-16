"""Model ground truth của benchmark: biên giá trị, id trùng, độ dài danh sách (architecture §15.2)."""

import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.value.ground_truth import (
    BenchmarkTruth,
    GapCheck,
    L4Declaration,
    MeasuredDistance,
    RobotProfile,
    TruthVersionConflictError,
    read_truth,
    write_truth,
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


@pytest.fixture
def database(tmp_path: Path) -> RuntimeDatabase:
    return RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")


def _truth(**overrides: object) -> BenchmarkTruth:
    body: dict[str, object] = {"include_in_benchmark": True, "notes": "bản thử"}
    body.update(overrides)
    return BenchmarkTruth(**body)  # type: ignore[arg-type]


def test_missing_document_reads_as_version_zero_with_defaults(database: RuntimeDatabase) -> None:
    stored = read_truth(database, "job-missing")

    assert stored.version == 0
    assert stored.updated_at is None
    assert stored.truth == BenchmarkTruth()


def test_write_from_version_zero_then_update_bumps_version(database: RuntimeDatabase) -> None:
    first = write_truth(database, "job-a", 0, _truth(notes="lần đầu"))
    second = write_truth(database, "job-a", 1, _truth(notes="lần hai"))

    assert (first.version, second.version) == (1, 2)
    stored = read_truth(database, "job-a")
    assert stored.version == 2
    assert stored.truth.notes == "lần hai"
    assert stored.updated_at is not None and stored.updated_at.tzinfo is not None


def test_stale_expected_version_is_rejected_and_keeps_the_stored_document(database: RuntimeDatabase) -> None:
    write_truth(database, "job-b", 0, _truth(notes="của A"))
    write_truth(database, "job-b", 1, _truth(notes="của A, vòng hai"))

    with pytest.raises(TruthVersionConflictError) as error:
        write_truth(database, "job-b", 1, _truth(notes="của B, ghi muộn"))

    assert (error.value.expected_version, error.value.current_version) == (1, 2)
    stored = read_truth(database, "job-b")
    assert (stored.version, stored.truth.notes) == (2, "của A, vòng hai")


def test_creating_twice_from_version_zero_conflicts(database: RuntimeDatabase) -> None:
    write_truth(database, "job-c", 0, _truth())

    with pytest.raises(TruthVersionConflictError):
        write_truth(database, "job-c", 0, _truth(notes="ghi thứ hai"))
    assert read_truth(database, "job-c").version == 1


def test_concurrent_writers_from_the_same_version_yield_one_winner(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'runtime.db'}"
    RuntimeDatabase(url)  # chạy migration một lần trước khi tranh chấp
    start = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def writer(name: str) -> None:
        start.wait()
        try:
            write_truth(RuntimeDatabase(url), "job-race", 0, _truth(notes=name))
            result = "won"
        except TruthVersionConflictError:
            result = "conflict"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=writer, args=(name,)) for name in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["conflict", "won"]
    stored = read_truth(RuntimeDatabase(url), "job-race")
    assert stored.version == 1
    assert stored.truth.notes in {"alpha", "beta"}
