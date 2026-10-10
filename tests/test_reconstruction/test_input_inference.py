"""Suy đơn vị và vai trò timestamp: chỉ suy khi duy nhất, mơ hồ thì không suy."""

from __future__ import annotations

import pytest

from src.models.contracts.input_assembly import InputAssetFormat, InputRole, StagedInputFile, TimestampUnit
from src.models.contracts.manifests import InputFile
from src.services.reconstruction.inputs.inference import infer_timestamp_roles, infer_timestamp_unit
from src.services.reconstruction.inputs.input_probe import InputProbe


def test_torwic_relative_seconds_at_ten_hz_are_seconds() -> None:
    """frame_times.txt thật của TorWIC: 1092 dòng, 0.0 → 109.0876 (tương đối từ 0, ~10 Hz)."""
    found = infer_timestamp_unit(count=1092, first=0.0, last=109.0876221656799, sensor="rgb")
    assert found is not None
    assert found.unit == TimestampUnit.SECONDS
    assert found.rate_hz == pytest.approx(10.0, rel=1e-2)


@pytest.mark.parametrize(
    ("scale", "unit"),
    [
        (1.0, TimestampUnit.SECONDS),
        (1e3, TimestampUnit.MILLISECONDS),
        (1e6, TimestampUnit.MICROSECONDS),
        (1e9, TimestampUnit.NANOSECONDS),
    ],
)
def test_the_same_ten_hz_capture_in_any_unit_is_recognized(scale: float, unit: TimestampUnit) -> None:
    count, step = 200, 0.1
    found = infer_timestamp_unit(
        count=count, first=5.0 * scale, last=(5.0 + step * (count - 1)) * scale, sensor="lidar"
    )
    assert found is not None and found.unit == unit
    assert found.rate_hz == pytest.approx(10.0, rel=1e-6)


@pytest.mark.parametrize(
    ("count", "first", "last"),
    [
        (301, 0.0, 1.0),  # 300 Hz theo giây, 300 kHz theo ms: ngoài dải ở mọi đơn vị → không suy
        (1000, 0.0, 0.0001),  # 10 triệu Hz theo giây, nhưng 10 kHz theo ms: cũng ngoài dải
        (1, 0.0, 1.0),
        (None, 0.0, 1.0),
        (10, 5.0, 5.0),
        (10, 9.0, 1.0),
        (10, float("nan"), 1.0),
    ],
)
def test_ambiguous_or_degenerate_timestamps_are_not_guessed(count: int | None, first: float, last: float) -> None:
    assert infer_timestamp_unit(count=count, first=first, last=last, sensor="lidar") is None


def test_two_samples_400_apart_are_milliseconds_not_unknown() -> None:
    """Chỉ một đơn vị cho tần số hợp lý (400 ms → 2,5 Hz), nên suy duy nhất là đúng."""
    found = infer_timestamp_unit(count=2, first=0.0, last=400.0, sensor="lidar")
    assert found is not None and found.unit == TimestampUnit.MILLISECONDS


def test_a_timestamp_file_longer_than_the_video_is_rejected() -> None:
    # 10 Hz trong 600 s nhưng video chỉ dài 60 s: đơn vị suy ra mâu thuẫn với video.
    args = {"count": 6000, "first": 0.0, "last": 599.9, "sensor": "rgb"}
    assert infer_timestamp_unit(**args) is not None
    assert infer_timestamp_unit(**args, video_duration_seconds=60.0) is None
    assert infer_timestamp_unit(**args, video_duration_seconds=600.0) is not None


def _file(file_id: str, fmt: InputAssetFormat) -> StagedInputFile:
    source = InputFile(
        original_name=file_id,
        media_type="text/plain",
        size_bytes=10,
        checksum="sha256:" + "a" * 64,
        artifact_uri=f"artifact://jobs/{file_id}/input/source",
        data_class="product_input",
    )
    return StagedInputFile(file_id=file_id, upload_id=f"up-{file_id}", source_file=source, observed_format=fmt)


def _probe(file_id: str, count: int) -> InputProbe:
    return InputProbe(
        file_id=file_id,
        source_checksum="sha256:" + "a" * 64,
        member_checksum=None,
        observed_format=InputAssetFormat.TIMESTAMP_ROWS,
        record_count=count,
        first_timestamp=0.0,
        last_timestamp=float(count),
    )


def _world(**counts: int):
    files = [_file(name, InputAssetFormat.TIMESTAMP_ROWS) for name in counts]
    probes = {name: _probe(name, count) for name, count in counts.items()}
    return files, probes


def test_with_a_trajectory_the_file_matching_the_pose_count_is_the_rgb_frame_times() -> None:
    files, probes = _world(times_a=6, times_b=30)
    roles = infer_timestamp_roles(files, probes, bound_file_ids=set(), pose_count=6, scan_count=6)
    assert roles == {InputRole.RGB_FRAME_TIMES: "times_a"}


def test_without_a_trajectory_the_file_matching_the_scan_count_is_the_lidar_scan_times() -> None:
    files, probes = _world(times_a=40, times_b=1500)
    roles = infer_timestamp_roles(files, probes, bound_file_ids=set(), pose_count=None, scan_count=40)
    assert roles == {InputRole.LIDAR_SCAN_TIMES: "times_a"}


def test_two_files_that_both_match_are_left_for_the_user_to_choose() -> None:
    files, probes = _world(times_a=6, times_b=6)
    assert infer_timestamp_roles(files, probes, bound_file_ids=set(), pose_count=6, scan_count=None) == {}


def test_nothing_is_inferred_without_a_count_to_match_or_for_already_bound_files() -> None:
    files, probes = _world(times_a=6)
    assert infer_timestamp_roles(files, probes, bound_file_ids=set(), pose_count=None, scan_count=None) == {}
    assert infer_timestamp_roles(files, probes, bound_file_ids={"times_a"}, pose_count=6, scan_count=6) == {}
    assert infer_timestamp_roles(files, probes, bound_file_ids=set(), pose_count=None, scan_count=1) == {}


def test_only_unclassified_timestamp_rows_are_candidates() -> None:
    files = [_file("traj", InputAssetFormat.TUM_TRAJECTORY), _file("times", InputAssetFormat.TIMESTAMP_ROWS)]
    probes = {"traj": _probe("traj", 6), "times": _probe("times", 6)}
    roles = infer_timestamp_roles(files, probes, bound_file_ids=set(), pose_count=6, scan_count=6)
    assert roles == {InputRole.RGB_FRAME_TIMES: "times"}
