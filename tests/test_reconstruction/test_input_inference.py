"""Suy đơn vị và vai trò timestamp: chỉ suy khi duy nhất, mơ hồ thì không suy."""

from __future__ import annotations

import pytest

from src.models.contracts.input_assembly import InputAssetFormat, InputRole, StagedInputFile, TimestampUnit
from src.models.contracts.manifests import InputFile
from src.services.reconstruction.inputs.inference import infer_timestamp_roles, infer_timestamp_unit
from src.services.reconstruction.inputs.input_probe import InputProbe


def test_torwic_relative_seconds_at_ten_hz_are_seconds() -> None:
    """frame_times.txt thật của TorWIC: 1092 dòng, 0.0 → 109.0876 (tương đối từ 0, ~10 Hz)."""
    found = infer_timestamp_unit(count=1092, first=0.0, last=109.0876221656799)
    assert found is not None
    assert found.unit == TimestampUnit.SECONDS
    assert found.rate_hz == pytest.approx(10.0, rel=1e-2)


def test_seconds_at_lidar_and_camera_rates_are_inferred() -> None:
    for hz in (2.0, 5.0, 10.0, 20.0, 30.0, 120.0):
        count = 200
        found = infer_timestamp_unit(count=count, first=5.0, last=5.0 + (count - 1) / hz)
        assert found is not None and found.unit == TimestampUnit.SECONDS, hz
        assert found.rate_hz == pytest.approx(hz, rel=1e-6)


@pytest.mark.parametrize("scale", [1e3, 1e6, 1e9], ids=["milliseconds", "microseconds", "nanoseconds"])
def test_the_same_ten_hz_capture_in_a_finer_unit_is_asked_not_guessed(scale: float) -> None:
    """10 Hz theo mili/micro/nano giây cũng có thể là 0,01 Hz theo đơn vị thô hơn: hỏi, không đoán."""
    count, step = 200, 0.1
    assert infer_timestamp_unit(count=count, first=5.0 * scale, last=(5.0 + step * (count - 1)) * scale) is None


@pytest.mark.parametrize("step_seconds", [5.0, 10.0, 25.0, 60.0])
def test_sparse_captures_in_seconds_are_not_read_as_milliseconds(step_seconds: float) -> None:
    """Lỗi auditor: scan thưa (đã lọc mẫu) theo giây bị đọc thành mili giây (vài trăm Hz)."""
    count = 20
    assert infer_timestamp_unit(count=count, first=0.0, last=step_seconds * (count - 1)) is None


@pytest.mark.parametrize(
    ("count", "first", "last"),
    [
        (2, 0.0, 400.0),  # hai mẫu chỉ có một khoảng: không chứng minh được tần số đều
        (20, 0.0, 190.0),  # 0,1 Hz theo giây HOẶC 100 Hz theo ms: cả hai khả dĩ → phải hỏi
        (4001, 0.0, 0.1),  # 40 kHz theo giây, 40 MHz theo ms: không đơn vị nào khả dĩ
        (1000, 0.0, 0.0001),  # 10 triệu Hz theo giây, nhưng 10 kHz theo ms: cũng ngoài dải
        (1, 0.0, 1.0),
        (None, 0.0, 1.0),
        (10, 5.0, 5.0),
        (10, 9.0, 1.0),
        (10, float("nan"), 1.0),
    ],
)
def test_ambiguous_or_degenerate_timestamps_are_not_guessed(count: int | None, first: float, last: float) -> None:
    assert infer_timestamp_unit(count=count, first=first, last=last) is None


def test_a_slow_capture_is_not_mistaken_for_a_fast_one_in_a_finer_unit() -> None:
    """Lỗi bug-scout: 20 mẫu cách nhau 10 đơn vị bị suy thành mili giây (100 Hz) dù có thể là 0,1 Hz theo giây."""
    assert infer_timestamp_unit(count=20, first=0.0, last=190.0) is None
    assert infer_timestamp_unit(count=20, first=0.0, last=1900.0) is None


def test_three_samples_are_the_minimum_to_call_a_rate_measured() -> None:
    found = infer_timestamp_unit(count=3, first=0.0, last=0.2)
    assert found is not None and found.unit == TimestampUnit.SECONDS


def test_a_timestamp_file_longer_than_the_video_is_rejected() -> None:
    # 10 Hz trong 600 s nhưng video chỉ dài 60 s: đơn vị suy ra mâu thuẫn với video.
    args = {"count": 6000, "first": 0.0, "last": 599.9}
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


# ---------------------------------------------------------------------------
# Vai trò khi có quỹ đạo camera, và cập nhật ước lượng cũ
# ---------------------------------------------------------------------------


def test_a_camera_trajectory_with_the_scan_count_makes_the_scan_times_role_ambiguous() -> None:
    """Lỗi bug-scout: chỉ bind quỹ đạo camera thì pose_count None, file thời điểm RGB bị gán nhầm là thời điểm scan."""
    from src.models.contracts.input_assembly import InputBinding
    from src.services.reconstruction.inputs.inference import timestamp_files_by_role

    files = [_file("cam_traj", InputAssetFormat.TUM_TRAJECTORY), _file("times", InputAssetFormat.TIMESTAMP_ROWS)]
    files += [_file(f"scan-{i}", InputAssetFormat.POINT_CLOUD_PCD) for i in range(6)]
    probes = {"cam_traj": _probe("cam_traj", 6), "times": _probe("times", 6)}
    bindings = [InputBinding(binding_id="cam", role=InputRole.CAMERA_TRAJECTORY, file_ids=["cam_traj"])]

    assert timestamp_files_by_role(files, probes, bindings) == {}


def test_a_file_bound_to_another_role_is_not_also_taken_as_legacy_frame_times() -> None:
    from src.models.contracts.input_assembly import InputBinding
    from src.services.reconstruction.inputs.inference import timestamp_files_by_role

    files = [_file("legacy", InputAssetFormat.RGB_FRAME_TIMES)]
    probes = {"legacy": _probe("legacy", 6)}
    bindings = [InputBinding(binding_id="x", role=InputRole.LIDAR_SCAN_TIMES, file_ids=["legacy"])]

    assert InputRole.RGB_FRAME_TIMES not in timestamp_files_by_role(files, probes, bindings)


def _declarations(**values: object):
    from src.models.contracts.input_assembly import InputAssemblyDeclarations

    return InputAssemblyDeclarations.model_validate(values)


def _scan_times_world(count: int, last: float):
    files = [_file("times", InputAssetFormat.TIMESTAMP_ROWS)] + [
        _file(f"scan-{i}", InputAssetFormat.POINT_CLOUD_PCD) for i in range(count)
    ]
    probe = _probe("times", count).model_copy(update={"first_timestamp": 0.0, "last_timestamp": last})
    return files, {"times": probe}


def test_a_stale_estimate_is_recomputed_or_dropped_but_a_declared_value_is_kept() -> None:
    from src.models.contracts.input_assembly import EvidenceProvenance, EvidenceValue
    from src.services.reconstruction.inputs.inference import enrich_timestamp_units

    stale = EvidenceValue(value=TimestampUnit.MILLISECONDS, provenance=EvidenceProvenance.ESTIMATED, method="old")
    declared = EvidenceValue(value=TimestampUnit.MICROSECONDS, provenance=EvidenceProvenance.DECLARED)

    files, probes = _scan_times_world(count=10, last=0.9)  # 10 Hz theo giây
    refreshed = enrich_timestamp_units(
        _declarations(lidar_timestamp_unit=stale.model_dump(mode="json")),
        files,
        probes,
        [],
        video_duration_seconds=None,
    )
    assert refreshed.lidar_timestamp_unit is not None
    assert refreshed.lidar_timestamp_unit.value == TimestampUnit.SECONDS  # ước lượng cũ (ms) được tính lại
    assert refreshed.lidar_timestamp_unit.provenance == EvidenceProvenance.ESTIMATED

    kept = enrich_timestamp_units(
        _declarations(lidar_timestamp_unit=declared.model_dump(mode="json")),
        files,
        probes,
        [],
        video_duration_seconds=None,
    )
    assert kept.lidar_timestamp_unit is not None and kept.lidar_timestamp_unit.value == TimestampUnit.MICROSECONDS

    unguessable_files, unguessable_probes = _scan_times_world(count=10, last=90.0)  # mơ hồ: 0,1 Hz hoặc 100 Hz
    dropped = enrich_timestamp_units(
        _declarations(lidar_timestamp_unit=stale.model_dump(mode="json")),
        unguessable_files,
        unguessable_probes,
        [],
        video_duration_seconds=None,
    )
    assert dropped.lidar_timestamp_unit is None


def test_enrichment_is_idempotent() -> None:
    from src.services.reconstruction.inputs.inference import enrich_timestamp_units

    files, probes = _scan_times_world(count=10, last=0.9)
    once = enrich_timestamp_units(_declarations(), files, probes, [], video_duration_seconds=None)
    twice = enrich_timestamp_units(once, files, probes, [], video_duration_seconds=None)
    assert once == twice
