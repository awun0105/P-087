"""Ngân sách suy từ số đo: chỉ lượt "trội hơn" mới cho chặn trên; thiếu số đo thì không đoán."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.config import Settings
from src.models.contracts.manifests import ExecutionError, JobStatus, StageId
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.processing.observed import (
    dominates,
    exhausted_before,
    load_usages,
    numeric_params,
    observed_budget,
)
from src.services.orchestration.processing.telemetry import ResourceUsage
from src.services.orchestration.projects.models import JobCreateInput
from tests.test_orchestration.test_prepared_queue import _registry

NOW = datetime(2026, 10, 2, tzinfo=UTC)
JOB = {"frames": 60.0, "splats": 500000.0}


def _usage(tool: str, vram: float | None, ram: float | None, **changes: object) -> ResourceUsage:
    fields: dict[str, object] = {
        "job_id": "job-a",
        "attempt_id": "attempt-a",
        "tool": tool,
        "config_checksum": "c",
        "runtime_manifest_checksum": "runtime-1",
        "params": JOB,
        "gpu_name": "T4",
        "shared_gpu": False,
        "started_at": NOW,
        "completed_at": NOW,
        "outcome": "completed",
        "exit_code": 0,
        "duration_seconds": 1.0,
        "sample_count": 1,
        "ram_sample_count": 1,
        "vram_sample_count": 1,
        "gpu_sample_count": 1,
        "scratch_sample_count": 1,
        "peak_ram_gb": ram,
        "peak_vram_gb": vram,
        "headroom_before": {},
    }
    return ResourceUsage(**{**fields, **changes})


def _budget(usages: list[ResourceUsage], tools: tuple[str, ...] = ("preview",), **changes: object) -> dict | None:
    arguments: dict = {"tools": tools, "params": JOB, "gpu_name": "T4", "runtime_manifest_checksum": "runtime-1"}
    return observed_budget(usages, **{**arguments, **changes})


def test_numeric_params_and_dominance() -> None:
    assert numeric_params({"a": 3, "b": 1.5, "model": "OPENCV", "flag": True}) == {"a": 3.0, "b": 1.5}
    assert dominates({"frames": 60, "splats": 600000}, JOB) and dominates(JOB, JOB)
    assert not dominates({"frames": 59, "splats": 900000}, JOB)  # nhỏ hơn ở một thông số là không trội
    assert not dominates({"frames": 60}, JOB)  # khác bộ thông số (cấu hình đổi schema) thì không so được


def test_no_dominating_measurement_means_unknown() -> None:
    assert _budget([]) is None
    smaller = _usage("preview", 1.0, 2.0, params={"frames": 30.0, "splats": 500000.0})
    assert _budget([smaller]) is None  # lượt nhẹ hơn không chặn trên được job nặng hơn
    assert _budget([_usage("preview", 1.0, 2.0)], gpu_name="A100") is None
    assert _budget([_usage("preview", 1.0, 2.0)], runtime_manifest_checksum="runtime-2") is None
    assert _budget([_usage("preview", 1.0, 2.0, outcome="failed", exit_code=1)]) is None


def test_same_config_takes_highest_seen_and_tightest_config_wins() -> None:
    same = [_usage("preview", 1.0, 2.0), _usage("preview", 1.4, 1.8)]  # video khác nhau, cùng cấu hình
    assert _budget(same) == {"vram": 1.4, "ram": 2.0}
    heavier = _usage("preview", 3.0, 6.0, params={"frames": 120.0, "splats": 1000000.0})
    assert _budget([heavier]) == {"vram": 3.0, "ram": 6.0}  # chỉ có lượt nặng hơn: vẫn là chặn trên hợp lệ
    assert _budget([*same, heavier]) == {"vram": 1.4, "ram": 2.0}  # có cấu hình sát hơn thì dùng nó


def test_every_tool_of_the_phase_must_be_measured() -> None:
    finalize, extract = _usage("finalize", 0.2, 0.8), _usage("scene_extract", 2.3, 4.6)
    assert _budget([finalize], tools=("finalize", "scene_extract")) is None
    assert _budget([finalize, extract], tools=("finalize", "scene_extract")) == {"vram": 2.3, "ram": 4.6}


def test_vram_without_per_process_numbers_uses_gpu_delta_only_when_alone() -> None:
    alone = _usage("preview", None, 2.0, gpu_used_before_gb=0.5, peak_gpu_used_gb=2.0)
    assert _budget([alone]) == {"vram": 1.5, "ram": 2.0}
    shared = alone.model_copy(update={"shared_gpu": True})
    unknown = alone.model_copy(update={"shared_gpu": None})
    assert _budget([shared]) is None and _budget([unknown]) is None  # mức GPU lúc chạy chung gồm cả job khác


def test_load_usages_skips_unreadable_rows_and_finds_exhaustion(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    database = registry.persistence.database
    failed = _usage("preview", 1.0, 2.0, outcome="failed", exit_code=1, exhausted=True)
    with database.transaction(write=True) as tx:
        for key, payload in (("a", failed.model_dump_json()), ("b", "{not json"), ("c", '{"schema_version": "9"}')):
            tx.execute(
                "INSERT INTO r2s_resource_usage(usage_id,job_id,recorded_at,payload) VALUES (?,?,?,?)",
                (key, "job-a", NOW.isoformat(), payload),
            )
    usages = load_usages(database)
    assert usages == [failed]
    assert exhausted_before(usages, "job-a") and not exhausted_before(usages, "job-b")


def _failed_attempt(tmp_path: Path) -> runner._Attempt:
    registry = _registry(tmp_path / "runtime")
    queued = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    job = registry.transition_job(queued.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    error = ExecutionError(
        error_code="VISUAL_PROCESS_FAILED", stage_id=StageId.VISUAL_RECON, human_message="tool died", retryable=True
    )
    job = registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.FAILED, error=error))
    workspace = tmp_path / "workers" / job.job_id / ("attempt-" + "a" * 32)
    workspace.mkdir(parents=True)
    return runner._Attempt(registry, Settings(product_worker_root=tmp_path / "workers"), job, workspace)


def _record_exhaustion(attempt: runner._Attempt) -> None:
    usage = _usage("preview", 1.0, 2.0, job_id=attempt.job.job_id, outcome="failed", exit_code=1, exhausted=True)
    runner._persist_usage(attempt, usage)
    attempt.exhausted = True


def test_out_of_memory_failure_requeues_once_then_stays_failed(tmp_path: Path) -> None:
    """Lần đầu: tự về hàng đợi (lượt sau chạy một mình). Lần hai: giữ FAILED, không lặp."""
    attempt = _failed_attempt(tmp_path)
    assert runner._requeue_if_exhausted(attempt) is None  # lỗi thường: không tự chạy lại
    assert attempt.registry.get_job(attempt.job.job_id).status == JobStatus.FAILED
    _record_exhaustion(attempt)
    requeued = runner._requeue_if_exhausted(attempt)
    assert requeued is not None and requeued.status == JobStatus.QUEUED
    assert requeued.config_checksum == attempt.job.config_checksum  # nguyên cấu hình
    # Lượt chạy lại (một mình) lại chết vì hết bộ nhớ.
    registry = attempt.registry
    job = registry.transition_job(requeued.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    error = ExecutionError(
        error_code="VISUAL_PROCESS_FAILED", stage_id=StageId.VISUAL_RECON, human_message="tool died", retryable=True
    )
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.FAILED, error=error))
    _record_exhaustion(attempt)
    assert runner._requeue_if_exhausted(attempt) is None
    assert registry.get_job(job.job_id).status == JobStatus.FAILED


def test_requeue_never_touches_a_job_that_is_not_failed_and_survives_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = _failed_attempt(tmp_path)
    _record_exhaustion(attempt)
    queued = attempt.registry.transition_job(attempt.job.job_id, TransitionRequest(target_status=JobStatus.QUEUED))
    assert runner._requeue_if_exhausted(attempt) is None  # người dùng đã tự bấm thử lại
    assert attempt.registry.get_job(queued.job_id) == queued
    monkeypatch.setattr(attempt.registry, "get_job", Mock(side_effect=RuntimeError("db down")))
    assert runner._requeue_if_exhausted(attempt) is None


def test_processing_seconds_counts_machine_time_only() -> None:
    """Thời gian xử lý = tổng các bước đã chạy xong; lượt lỗi và lượt chạy lại cũ không cộng dồn."""
    from datetime import timedelta

    from src.services.orchestration.processing.observed import processing_seconds

    later = NOW + timedelta(hours=3)  # ba giờ chờ người dùng xác nhận tỉ lệ nằm giữa hai pha, không được tính
    usages = [
        _usage("prepare", None, 0.2, duration_seconds=60.0),
        _usage("preview", 1.0, 1.0, duration_seconds=400.0),
        _usage("finalize", 0.2, 0.5, duration_seconds=90.0, started_at=later, completed_at=later),
        _usage("finalize", 0.2, 0.5, duration_seconds=80.0, outcome="failed", exit_code=1),
        _usage("preview", 1.0, 1.0, duration_seconds=300.0, completed_at=later),  # chạy lại: thay lượt trước
        _usage("prepare", None, 0.2, duration_seconds=10.0, job_id="job-b"),
        _usage("preview", 1.0, 1.0, duration_seconds=5.0, job_id="job-c", outcome="failed", exit_code=1),
    ]
    assert processing_seconds(usages) == {"job-a": 60.0 + 300.0 + 90.0, "job-b": 10.0}


def test_observed_for_config_returns_none_when_a_required_tool_is_unmeasured() -> None:
    from src.services.orchestration.processing.observed import observed_for_config

    preview = _usage("preview", 1.5, 2.0)
    # Chỉ có preview (thiếu finalize và scene_extract) -> None
    assert (
        observed_for_config(
            [preview],
            params=JOB,
            gpu_name="T4",
            runtime_manifest_checksum="runtime-1",
        )
        is None
    )


def test_observed_for_config_uses_resource_maxima_across_phases() -> None:
    from src.services.orchestration.processing.observed import observed_for_config

    preview = _usage("preview", 1.5, 2.0)
    finalize = _usage("finalize", 0.5, 1.0)
    extract = _usage("scene_extract", 2.2, 4.5)
    # Đủ cả preview, finalize, scene_extract -> max(preview, finalize/extract)
    # vram: max(1.5, 2.2) = 2.2
    # ram: max(2.0, 4.5) = 4.5
    assert observed_for_config(
        [preview, finalize, extract],
        params=JOB,
        gpu_name="T4",
        runtime_manifest_checksum="runtime-1",
    ) == {"vram": 2.2, "ram": 4.5}
