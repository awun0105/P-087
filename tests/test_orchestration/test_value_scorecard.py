"""Bảng metric giá trị: công người, can thiệp, phút máy, P2/P3/P4, xuất CSV/Markdown (architecture §15.1–§15.3).

Phần tính toán chạy trên dữ liệu dựng tay (sự kiện, usage, collision giả), không cần scene thật.
"""

import csv
import io
import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
import trimesh

from src.services.orchestration.processing.telemetry import ResourceUsage
from src.services.orchestration.value.events import ValueEvent
from src.services.orchestration.value.ground_truth import (
    BenchmarkTruth,
    GapCheck,
    MeasuredDistance,
    RobotProfile,
)
from src.services.orchestration.value.measure import CollisionWorld, MoveResult
from src.services.orchestration.value.scorecard import (
    CSV_HEADER,
    P2,
    P3,
    P4,
    Check,
    Figure,
    ValueScorecard,
    benchmark_summary,
    compute_p2,
    compute_p3,
    csv_document,
    declared,
    first_human_change_after,
    hands_on,
    hardware_and_cost,
    interventions,
    level_from_checks,
    machine_minutes,
    north_star_block,
    scorecard_markdown,
    unavailable,
    unavailable_p2,
)

_JOB = "job-score"
_T0 = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
_ROBOT = RobotProfile(width_m=0.6, safety_margin_m=0.05, height_min_m=0.05, height_max_m=1.2)


def _event(kind: str, at: datetime, **payload: object) -> ValueEvent:
    return ValueEvent(
        event_id=f"e-{kind}-{at.isoformat()}", job_id=_JOB, at=at, kind=kind, actor_id=None, payload=payload
    )  # type: ignore[arg-type]


def _batch(ended: datetime, seconds: float) -> ValueEvent:
    return _event(
        "operator_time",
        ended,
        session_key="session-abcdef12",
        surface="studio",
        started_at=(ended - timedelta(seconds=seconds)).isoformat(),
        ended_at=ended.isoformat(),
        active_seconds=seconds,
    )


def _usage(
    tool: str, *, seconds: float = 60.0, gpu: str | None = "T4", at: datetime = _T0, **changes: object
) -> ResourceUsage:
    fields: dict[str, object] = {
        "job_id": _JOB,
        "attempt_id": f"attempt-{tool}-{at.isoformat()}",
        "tool": tool,
        "config_checksum": "c",
        "runtime_manifest_checksum": "runtime-1",
        "gpu_name": gpu,
        "shared_gpu": False,
        "started_at": at,
        "completed_at": at + timedelta(seconds=seconds),
        "outcome": "completed",
        "exit_code": 0,
        "duration_seconds": seconds,
        "sample_count": 1,
        "ram_sample_count": 1,
        "vram_sample_count": 1,
        "gpu_sample_count": 1,
        "scratch_sample_count": 1,
        "peak_ram_gb": 8.0,
        "peak_vram_gb": 10.0,
        "headroom_before": {},
    }
    return ResourceUsage(**{**fields, **changes})


# --- Công người ---------------------------------------------------------------------------------------------------------


def test_hands_on_splits_before_and_after_the_first_ready_moment() -> None:
    events = [_batch(_T0 + timedelta(minutes=1), 60), _batch(_T0 + timedelta(minutes=10), 120)]

    total, before, after = hands_on(events, ready_at=_T0 + timedelta(minutes=5), currently_ready=True)

    assert (total.value, before.value, after.value) == (3.0, 1.0, 2.0)
    assert total.provenance == before.provenance == after.provenance == "measured"


def test_hands_on_without_batches_is_unavailable_never_zero() -> None:
    total, before, after = hands_on([], ready_at=None, currently_ready=None)

    assert total.value is None and total.provenance == "unavailable"
    assert before.provenance == after.provenance == "unavailable"


def test_hands_on_before_ready_when_the_scene_is_still_awaiting_review() -> None:
    events = [_batch(_T0 + timedelta(minutes=2), 60)]

    total, before, after = hands_on(events, ready_at=None, currently_ready=False)

    assert before.value == total.value == 1.0
    assert after.provenance == "unavailable"
    assert "chưa đạt" in (after.note or "")


# --- Can thiệp ----------------------------------------------------------------------------------------------------------


def test_only_human_origin_edits_and_requests_count_as_interventions() -> None:
    events = [
        _event("scene_edit", _T0, operation="transform_edit", origin="human", scene_revision="rev-2"),
        _event("scene_edit", _T0, operation="objectify", origin="system", scene_revision="rev-3"),
        _event("scene_edit", _T0, operation="weird_op", origin="unknown", scene_revision="rev-4"),
        _event("scene_request", _T0, mode="geometry", origin="human", base_revision="rev-4"),
        _event("scene_request", _T0, mode="geometry", origin="system", base_revision="rev-4"),
        _event("walk_session", _T0, outcome="completed", scene_revision="rev-4"),
    ]

    counts, total = interventions(events)

    assert counts == {"transform_edit": 1, "unknown": 1, "request:geometry": 1}
    assert total.value == 2 and total.provenance == "measured"


def test_no_intervention_events_is_unavailable() -> None:
    counts, total = interventions([])

    assert counts == {} and total.provenance == "unavailable"


# --- Phút máy, GPU, chi phí ---------------------------------------------------------------------------------------------


def test_machine_minutes_adds_every_scene_step_but_keeps_only_the_latest_pipeline_run() -> None:
    usages = [
        _usage("preview", seconds=600, at=_T0),
        _usage("preview", seconds=300, at=_T0 + timedelta(hours=1)),  # chạy lại cùng bước: chỉ lượt này được tính
        _usage("scene.geometry", seconds=120, at=_T0 + timedelta(hours=2)),
        _usage("scene.geometry", seconds=180, at=_T0 + timedelta(hours=3)),  # scene.* cộng dồn
    ]

    figure = machine_minutes(usages, _JOB)

    assert figure.value == 10.0 and figure.provenance == "measured"


def test_cost_is_declared_from_gpu_hours_and_the_rate() -> None:
    usages = [_usage("preview", seconds=3600, gpu="RTX 4090")]

    hardware, gpu_hours, cost = hardware_and_cost(usages, rate_usd_per_hour=0.5)

    assert hardware["gpu_name"] == "RTX 4090"
    assert gpu_hours.value == 1.0 and gpu_hours.provenance == "measured"
    assert cost.value == 0.5 and cost.provenance == "declared"


def test_cost_without_a_declared_rate_is_unavailable() -> None:
    _, gpu_hours, cost = hardware_and_cost([_usage("preview", seconds=3600)], rate_usd_per_hour=None)

    assert gpu_hours.provenance == "measured"
    assert cost.value is None and cost.provenance == "unavailable"


def test_cpu_only_job_has_no_gpu_hours_or_cost() -> None:
    _, gpu_hours, cost = hardware_and_cost([_usage("preview", seconds=60, gpu=None)], rate_usd_per_hour=0.5)

    assert gpu_hours.provenance == "unavailable" and cost.provenance == "unavailable"


def test_hardware_without_a_machine_snapshot_stays_null_but_peaks_are_measured() -> None:
    hardware, _, _ = hardware_and_cost([_usage("preview", seconds=60)], rate_usd_per_hour=None)

    assert hardware["vram_gb"] is None and hardware["cpu_count"] is None and hardware["ram_gb"] is None
    assert hardware["peak_vram_gb"] == 10.0 and hardware["peak_ram_gb"] == 8.0


def test_hardware_comes_from_the_job_benchmark_machine_snapshot() -> None:
    from src.services.orchestration.processing.models import MachineCapability

    machine = MachineCapability(
        worker_id="w1",
        measured_at=_T0,
        gpu_name="RTX 4090",
        vram_total_gb=24.0,
        cpu_count=16,
        ram_total_gb=64.0,
        disk_free_gb=100.0,
    )
    hardware, _, _ = hardware_and_cost([_usage("preview", seconds=60, gpu=None)], None, machine)

    assert hardware["gpu_name"] == "RTX 4090"  # không có lượt GPU nào: lấy tên GPU của snapshot
    assert (hardware["vram_gb"], hardware["cpu_count"], hardware["ram_gb"]) == (24.0, 16, 64.0)


def test_layout_change_through_the_queue_starts_the_retest_clock() -> None:
    """Đổi bố trí trên Ready bằng chỉnh vùng chỉ có scene_request của người; revision kết quả là system."""
    request = _event("scene_request", _T0 + timedelta(minutes=2), mode="region", origin="human")
    system_edit = _event("scene_edit", _T0 + timedelta(minutes=5), operation="object_geometry_build", origin="system")
    auto = _event("scene_request", _T0 + timedelta(minutes=1), mode="geometry", origin="system")

    assert first_human_change_after([auto, request, system_edit], _T0) == _T0 + timedelta(minutes=2)
    assert first_human_change_after([auto, system_edit], _T0) is None


def test_north_star_block_puts_the_pieces_together() -> None:
    ns = north_star_block(
        events=[_batch(_T0 + timedelta(minutes=1), 60)],
        usages=[_usage("preview", seconds=60)],
        job_id=_JOB,
        ready_at=None,
        currently_ready=True,
        rate_usd_per_hour=None,
    )

    assert ns.hands_on_minutes.value == 1.0
    assert ns.machine_minutes.value == 1.0
    assert ns.cost_usd.provenance == "unavailable"
    assert ns.interventions_total.provenance == "unavailable"


# --- Điểm bậc L0–L4 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("passed_levels", [(), (1,), (1, 2), (1, 2, 3), (1, 2, 3, 4)])
def test_level_is_the_highest_fully_passed_rung(passed_levels: tuple[int, ...]) -> None:
    checks = [Check(level, True, "") for level in passed_levels]
    expected = len(passed_levels)
    if expected < 4:
        checks.append(Check(expected + 1, False, f"L{expected + 1} còn thiếu"))

    result = level_from_checks(checks)

    assert result.level == expected
    if expected == 4:
        assert result.reasons == []
    else:
        assert result.reasons == [f"L{expected + 1} còn thiếu"]


def test_reasons_list_only_the_next_rungs_missing_conditions() -> None:
    checks = [
        Check(1, True, ""),
        Check(2, False, "chưa có walk hoàn tất trên revision hiện tại"),
        Check(2, False, "layout A còn 1 khe bỏ sót vật cản"),
        Check(3, False, "chưa có gói mô phỏng"),
    ]

    result = level_from_checks(checks)

    assert result == P4(
        level=1, reasons=["chưa có walk hoàn tất trên revision hiện tại", "layout A còn 1 khe bỏ sót vật cản"]
    )


# --- P2 và P3 -----------------------------------------------------------------------------------------------------------


def _box_world(*boxes: tuple[str, tuple[float, float, float], tuple[float, float, float]]) -> CollisionWorld:
    meshes, owners = [], []
    for owner, center, extents in boxes:
        box = trimesh.creation.box(extents=extents)
        box.apply_translation(center)
        meshes.append(box)
        owners.extend([owner] * len(box.faces))
    merged = trimesh.util.concatenate(meshes)
    return CollisionWorld(
        mesh=merged,
        face_owner=np.array(owners, dtype=object),
        solid_owners=frozenset(owner for owner, _, _ in boxes if owner),
        face_part=np.arange(len(owners), dtype=np.int64),
        solid_parts=frozenset(),
    )


def _two_walls_world() -> CollisionWorld:
    return _box_world(("", (-0.9, 0.0, 0.5), (1.0, 2.0, 1.0)), ("", (0.9, 0.0, 0.5), (1.0, 2.0, 1.0)))


def _truth(**overrides: object) -> BenchmarkTruth:
    body: dict[str, object] = {
        "robot": _ROBOT,
        "gaps": [
            GapCheck(id="g-open", label="cửa", layout="A", a=(-0.5, 0, 0.5), b=(0.5, 0, 0.5), real_passable=True),
            GapCheck(id="g-blocked", label="lối", layout="A", a=(-0.5, 0, 0.5), b=(0.5, 0, 0.5), real_passable=False),
        ],
        "distances": [MeasuredDistance(id="d1", label="bàn", a=(0, 0, 0), b=(1, 0, 0), real_m=0.98)],
        "layouts": {},
    }
    body.update(overrides)
    return BenchmarkTruth(**body)  # type: ignore[arg-type]


def test_p2_counts_agreement_misses_and_false_obstacles_and_reports_the_error_as_declared() -> None:
    truth = _truth()

    p2 = compute_p2(truth, lambda revision: _two_walls_world(), key_with_collider=[True, False])

    assert p2.gaps_checked == 0  # khe chưa gắn layout thì không đo, không đếm
    truth_with_layout = _truth(layouts={"A": {"scene_revision": "rev-2", "tagged_at": _T0}})
    p2 = compute_p2(truth_with_layout, lambda revision: _two_walls_world(), key_with_collider=[True, False])
    assert p2.gaps_checked == 2
    assert p2.gaps_agree == 1
    assert p2.missed_obstacles == 1  # g-blocked: thật không qua nhưng mô phỏng qua
    assert p2.false_obstacles == 0
    assert p2.key_obstacles_with_collider == "1/2"
    assert p2.max_distance_error_cm.provenance == "declared"
    assert p2.max_distance_error_cm.value == 2.0


def test_p2_missing_robot_with_gaps_raises_so_the_caller_marks_it_unavailable() -> None:
    with pytest.raises(ValueError, match="robot"):
        compute_p2(
            _truth(robot=None, layouts={"A": {"scene_revision": "rev-2", "tagged_at": _T0}}),
            lambda revision: _two_walls_world(),
            [],
        )


def test_p2_unavailable_block_has_no_zero_counts_pretending_to_be_measurements() -> None:
    p2 = unavailable_p2("chưa có ground truth")

    assert p2.unavailable_reason == "chưa có ground truth"
    assert p2.max_distance_error_cm.provenance == "unavailable"


def test_p3_retest_minutes_run_from_the_first_human_edit_to_the_first_completed_walk_on_layout_b() -> None:
    truth = _truth(
        layouts={"A": {"scene_revision": "rev-2", "tagged_at": _T0}, "B": {"scene_revision": "rev-3", "tagged_at": _T0}}
    )
    edit = _T0 + timedelta(minutes=4)
    walk = _T0 + timedelta(minutes=10)

    p3 = compute_p3(
        truth,
        first_human_edit_after=lambda moment: edit if moment <= edit else None,
        walk_completed_after=lambda revision, moment: walk if revision == "rev-3" and walk > moment else None,
        moves_of=lambda: [
            MoveResult(object_id="a", old_cleared=True, new_present=True, passed=True),
            MoveResult(object_id="b", old_cleared=True, new_present=False, passed=False),
        ],
    )

    assert p3.edit_to_retest_minutes.value == 6.0
    assert p3.edit_to_retest_minutes.provenance == "measured"
    assert p3.consistent is False


def test_p3_without_layout_b_is_unavailable_and_consistency_is_none() -> None:
    truth = _truth(layouts={"A": {"scene_revision": "rev-2", "tagged_at": _T0}})

    p3 = compute_p3(truth, lambda moment: None, lambda revision, moment: None, lambda: [])

    assert p3.edit_to_retest_minutes.provenance == "unavailable"
    assert p3.consistent is None


def test_p3_no_completed_walk_after_the_edit_is_unavailable_not_zero() -> None:
    truth = _truth(
        layouts={"A": {"scene_revision": "rev-2", "tagged_at": _T0}, "B": {"scene_revision": "rev-3", "tagged_at": _T0}}
    )

    p3 = compute_p3(truth, lambda moment: _T0 + timedelta(minutes=1), lambda revision, moment: None, lambda: [])

    assert p3.edit_to_retest_minutes.value is None
    assert p3.edit_to_retest_minutes.provenance == "unavailable"


# --- Hiệu năng: 50k tam giác dưới 3 giây ---------------------------------------------------------------------------------


def test_gap_block_on_a_grid_of_about_fifty_thousand_triangles_finishes_in_three_seconds() -> None:
    size = 158
    xs = np.linspace(-4.0, 4.0, size)
    ys = np.linspace(-4.0, 4.0, size)
    grid_x, grid_y = np.meshgrid(xs, ys)
    vertices = np.column_stack([grid_x.ravel(), grid_y.ravel(), np.full(size * size, 0.5)])
    faces = []
    for row in range(size - 1):
        for col in range(size - 1):
            a = row * size + col
            faces.append([a, a + 1, a + size])
            faces.append([a + 1, a + size + 1, a + size])
    faces_array = np.array(faces)
    count = len(faces_array)
    walls = _two_walls_world()
    mesh = trimesh.util.concatenate([trimesh.Trimesh(vertices, faces_array, process=False), walls.mesh])
    owners = np.array([""] * count + list(walls.face_owner), dtype=object)
    world = CollisionWorld(
        mesh=mesh,
        face_owner=owners,
        solid_owners=frozenset(),
        face_part=np.full(len(owners), -1, dtype=np.int64),
        solid_parts=frozenset(),
    )
    truth = _truth(layouts={"A": {"scene_revision": "rev-2", "tagged_at": _T0}})

    started = time.perf_counter()
    p2 = compute_p2(truth, lambda revision: world, key_with_collider=[])
    elapsed = time.perf_counter() - started

    assert count > 45_000
    assert p2.gaps_checked == 2
    assert elapsed < 3.0


# --- Xuất CSV và Markdown -----------------------------------------------------------------------------------------------


def _card(**overrides: object) -> ValueScorecard:
    ns = north_star(_usage("preview", seconds=600))
    body: dict[str, object] = {
        "job_id": _JOB,
        "scene_name": "Phòng thử 1",
        "generated_at": _T0,
        "scene_revision": "rev-2",
        "data_source": "self_capture",
        "notes": "ghi chú",
        "north_star": ns,
        "p2": unavailable_p2("chưa có ground truth"),
        "p3": P3(
            edit_to_retest_minutes=unavailable("chưa có ground truth", "phút"),
            moves=[],
            consistent=None,
            unavailable_reason="chưa có ground truth",
        ),
        "p4": P4(level=0, reasons=["chưa xác nhận tỉ lệ mét cho revision hiện tại"]),
        "manual_baseline_minutes": unavailable("chưa khai báo mốc làm tay", "phút"),
    }
    body.update(overrides)
    return ValueScorecard(**body)  # type: ignore[arg-type]


def north_star(usage) -> object:  # noqa: ANN001 - chỉ để dựng NorthStar cho thẻ mẫu
    return north_star_block(
        events=[_batch(_T0 + timedelta(minutes=1), 120)],
        usages=[usage],
        job_id=_JOB,
        ready_at=None,
        currently_ready=True,
        rate_usd_per_hour=None,
    )


def test_csv_has_a_utf8_bom_fourteen_columns_in_playbook_order_and_empty_cells_for_unavailable() -> None:
    text = csv_document([_card()])

    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.removeprefix("﻿"))))
    assert rows[0] == CSV_HEADER and len(rows[0]) == 14
    row = dict(zip(CSV_HEADER, rows[1], strict=True))
    assert row["Scene"] == "Phòng thử 1"
    assert row["Nguồn"] == "Tự quay"
    assert row["Máy (ph)"] == "10.0"
    assert row["Khe khớp"] == "" and row["Bỏ sót / Giả"] == ""  # P2 chưa có → ô trống, không phải 0
    assert row["Bậc"] == "L0"
    assert row["Làm tay (ph)"] == ""


def test_markdown_starts_with_the_five_metric_table_and_marks_p2_as_measured_against_tape() -> None:
    measured_p2 = P2(
        gaps_checked=1,
        gaps_agree=1,
        missed_obstacles=0,
        false_obstacles=0,
        gap_results=[],
        max_distance_error_cm=Figure(value=1.0, unit="cm", provenance="declared"),
        distance_results=[],
        key_obstacles_with_collider="1/1",
    )
    text = scorecard_markdown(_card(p2=measured_p2))

    table = [line for line in text.splitlines() if line.startswith("| ")][:8]
    assert table[0].startswith("| Metric")
    assert any("Chính" in line for line in table)
    assert any("P2" in line and "đo, so với số thước" in line for line in text.splitlines())
    assert "đo, so với số thước" not in scorecard_markdown(_card())  # P2 chưa đo thì không gắn nhãn đo
    assert any("P3" in line for line in table)
    assert any("P4" in line for line in table)
    assert any("Làm tay" in line for line in table)
    assert "Chưa lên bậc kế tiếp" in text


def test_benchmark_summary_uses_medians_and_counts_only_measured_values() -> None:
    cards = [
        _card(north_star=north_star(_usage("preview", seconds=600, gpu="T4"))),
        _card(north_star=north_star(_usage("preview", seconds=1200, gpu="T4"))),
        _card(
            north_star=north_star(_usage("preview", seconds=600, gpu="A100")),
            p4=P4(level=3, reasons=[]),
            manual_baseline_minutes=declared(45.0, "phút"),
        ),
    ]

    summary = benchmark_summary(cards)

    assert summary.scenes == 3
    assert summary.machine_median_minutes_by_gpu == {"A100": 10.0, "T4": 15.0}
    assert summary.machine_n_by_gpu == {"A100": 1, "T4": 2}
    assert summary.manual_median_minutes == 45.0 and summary.manual_n == 1
    assert summary.scenes_at_least_l3 == 1 and summary.scenes_at_least_l2 == 1
    assert summary.gaps_total == 0  # không có scene nào có P2 đo được


def test_summary_counts_p2_only_for_scenes_with_measured_gaps() -> None:
    measured_p2 = P2(
        gaps_checked=2,
        gaps_agree=1,
        missed_obstacles=1,
        false_obstacles=0,
        gap_results=[],
        max_distance_error_cm=Figure(value=1.0, unit="cm", provenance="declared"),
        distance_results=[],
        key_obstacles_with_collider="1/1",
    )

    summary = benchmark_summary([_card(p2=measured_p2), _card()])

    assert (summary.gaps_agree_total, summary.gaps_total, summary.missed_total) == (1, 2, 1)


def test_markdown_escapes_pipes_and_newlines_in_the_scene_name() -> None:
    from src.services.orchestration.value.scorecard import _md

    assert _md("Kho | A\nlối 2") == "Kho \\| A lối 2"


def test_job_machine_reads_the_latest_attempt_snapshot_terminal_first(tmp_path) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from src.services.orchestration.benchmark import PipelineRuntimeBenchmark
    from src.services.orchestration.processing.models import MachineCapability
    from src.services.orchestration.value.scorecard import _job_machine

    def snapshot(attempt: int, gpu: str | None) -> bytes:
        machine = (
            MachineCapability(
                worker_id="w", measured_at=_T0, gpu_name=gpu, cpu_count=8, ram_total_gb=32.0, disk_free_gb=1.0
            )
            if gpu
            else None
        )
        return (
            PipelineRuntimeBenchmark(
                job_id=_JOB,
                project_id="p",
                attempt=attempt,
                recorded_at=_T0,
                status="SUCCEEDED",
                stages=[],
                config_checksum="c",
                machine=machine,
            )
            .model_dump_json()
            .encode()
        )

    files = {
        f"artifact://jobs/{_JOB}/benchmark/pipeline_runtime/attempt-1-terminal.json": snapshot(1, "T4"),
        f"artifact://jobs/{_JOB}/benchmark/pipeline_runtime/attempt-2-partial.json": snapshot(2, "L4"),
        f"artifact://jobs/{_JOB}/benchmark/pipeline_runtime/attempt-3-terminal.json": snapshot(3, None),
    }

    def locate(uri: str):  # noqa: ANN202
        if uri not in files:
            return None
        path = tmp_path / uri.rsplit("/", 1)[-1]
        path.write_bytes(files[uri])
        return path

    registry = SimpleNamespace(
        list_job_attempts=lambda job_id: [SimpleNamespace(attempt=n) for n in (1, 2, 3)],
        runtime_resolver=SimpleNamespace(locate=locate),
    )

    machine = _job_machine(registry, _JOB)  # type: ignore[arg-type]

    # attempt 3 không có snapshot máy → lùi về attempt 2 (chỉ có partial).
    assert machine is not None and machine.gpu_name == "L4"


def test_no_gap_measured_yet_gives_empty_gap_cells_not_zero() -> None:
    no_gaps = P2(
        gaps_checked=0,
        gaps_agree=0,
        missed_obstacles=0,
        false_obstacles=0,
        gap_results=[],
        max_distance_error_cm=Figure(value=1.0, unit="cm", provenance="declared"),
        distance_results=[],
        key_obstacles_with_collider="1/1",
    )
    card = _card(p2=no_gaps)

    rows = list(csv.reader(io.StringIO(csv_document([card]).removeprefix("﻿"))))
    row = dict(zip(CSV_HEADER, rows[1], strict=True))
    assert row["Khe khớp"] == "" and row["Bỏ sót / Giả"] == ""
    markdown = scorecard_markdown(card)
    assert "0/0" not in markdown
    assert "chưa có khe kiểm nào được đo" in markdown


def test_markdown_marks_l4_as_declared() -> None:
    l4 = _card().model_copy(update={"p4": P4(level=4, reasons=[])})
    line = next(item for item in scorecard_markdown(l4).splitlines() if item.startswith("| P4"))

    assert line.rstrip().endswith("| khai báo |")
    assert scorecard_markdown(_card()).count("| đo |") >= 1


def test_benchmark_markdown_without_gaps_does_not_claim_a_zero_measurement() -> None:
    from src.services.orchestration.value.scorecard import benchmark_markdown

    assert "Khe khớp: —" in benchmark_markdown([], benchmark_summary([]))
    measured = benchmark_summary([]).model_copy(update={"gaps_agree_total": 1, "gaps_total": 2})
    assert "Khe khớp: 1/2" in benchmark_markdown([], measured)
