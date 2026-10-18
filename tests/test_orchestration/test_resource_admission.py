"""Durable queue fixture proof: chờ/tiếp tục/cancel giữ config và provenance."""

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.models.contracts.manifests import JobManifest, JobStatus, StageId
from src.services.orchestration.jobs import admission
from src.services.orchestration.jobs.admission import ResourceAdmission, resource_wait
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.progress import job_progress
from src.services.orchestration.jobs.worker_cli import dispatch_next
from src.services.orchestration.processing import build_job_config, job_config_reference, load_presets, preset_values
from src.services.orchestration.processing.capability import GpuReading
from src.services.orchestration.processing.observed import Phase, numeric_params
from src.services.orchestration.processing.telemetry import ResourceUsage
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry
from tests.test_orchestration.test_metric_confirmation_record import _confirmation
from tests.test_orchestration.test_prepared_queue import _attach_frames, _frame_stage, _registry

PRESETS = Path(__file__).resolve().parents[2] / "configs/product/processing_presets_v1.json"


def _queued(tmp_path: Path) -> tuple[ProjectRegistry, JobManifest, ResourceAdmission]:
    registry = _registry(tmp_path / "runtime")
    presets, checksum = load_presets(PRESETS)
    config = build_job_config(presets, checksum, preset_values(presets, "minimum_quality"), None)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"), config)
    job = _attach_frames(registry, job, _frame_stage(job.job_id))
    gate = ResourceAdmission(
        registry,
        Settings(
            _env_file=None,
            product_processing_config=PRESETS,
            product_runtime_manifest=PRESETS.parents[2] / "fixtures/mock_job/runtime_manifest.json",
            product_worker_root=tmp_path / "workers",
        ),
    )
    return registry, job, gate


@pytest.mark.parametrize("free", [0.01, None])
def test_insufficient_or_unknown_resource_waits_without_claim_or_config_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, free: float | None
) -> None:
    registry, job, gate = _queued(tmp_path)
    monkeypatch.setattr(
        admission,
        "measure_live_headroom",
        lambda path: {"vram_free_gb": 100.0, "ram_available_gb": free, "disk_free_gb": 100.0},
    )
    config_path = registry.runtime_resolver.require(job_config_reference(job.job_id, job.config_checksum))
    original = config_path.read_bytes()
    events = registry.list_job_attempts(job.job_id)

    def unexpected(*args: object, **kwargs: object) -> JobManifest:
        raise AssertionError("thiếu tài nguyên không được claim/chạy tool")

    assert not dispatch_next(registry, runner=unexpected, admission=gate)
    assert not dispatch_next(registry, runner=unexpected, admission=gate)
    assert registry.get_job(job.job_id) == job and config_path.read_bytes() == original
    assert registry.list_job_attempts(job.job_id) == events
    wait = resource_wait(gate.database, job)
    assert wait is not None and wait.waiting_on == ["ram"]
    progress = job_progress(job, events, False, wait)
    assert progress.waiting_for == "resources" and progress.status == "QUEUED"
    assert all(stage.state == "pending" for stage in progress.stages if stage.stage_id != "ST-FRAME-EXTRACT")


def test_resource_recovery_automatically_dispatches_same_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, gate = _queued(tmp_path)
    current = {"vram_free_gb": 100.0, "ram_available_gb": 0.01, "disk_free_gb": 100.0}
    monkeypatch.setattr(admission, "measure_live_headroom", lambda path: current)
    assert not dispatch_next(registry, admission=gate)
    calls: list[str] = []

    def run(job_id: str, uri: str, *, expected_checksum: str) -> JobManifest:
        calls.append(job_id)
        assert expected_checksum == job.job_manifest_checksum
        return registry.transition_job(
            job_id, TransitionRequest(target_status=JobStatus.RUNNING), expected_checksum=expected_checksum
        )

    current["ram_available_gb"] = 100.0
    assert dispatch_next(registry, runner=run, admission=gate)
    running = registry.get_job(job.job_id)
    assert calls == [job.job_id] and running.config_checksum == job.config_checksum
    assert resource_wait(gate.database, running) is None


def test_cancelled_job_is_not_resumed_and_old_observation_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, gate = _queued(tmp_path)
    monkeypatch.setattr(
        admission,
        "measure_live_headroom",
        lambda path: {"vram_free_gb": 100.0, "ram_available_gb": 0.01, "disk_free_gb": 100.0},
    )
    assert not dispatch_next(registry, admission=gate)
    cancelled = registry.transition_job(
        job.job_id, TransitionRequest(target_status=JobStatus.CANCELLED), expected_checksum=job.job_manifest_checksum
    )
    assert resource_wait(gate.database, cancelled) is None
    assert not dispatch_next(registry, admission=gate)
    assert registry.get_job(job.job_id).status == JobStatus.CANCELLED


def test_stale_wait_snapshot_is_not_presented_as_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, gate = _queued(tmp_path)
    monkeypatch.setattr(
        admission,
        "measure_live_headroom",
        lambda path: {"vram_free_gb": None, "ram_available_gb": None, "disk_free_gb": None},
    )
    assert not gate(job)
    wait = resource_wait(gate.database, job)
    assert wait is not None
    wait.checked_at = datetime.now(UTC) - timedelta(minutes=16)
    with gate.database.transaction(write=True) as tx:
        tx.execute("UPDATE r2s_resource_waits SET payload=? WHERE job_id=?", (wait.model_dump_json(), job.job_id))
    assert resource_wait(gate.database, job) is None


def test_confirmed_job_waits_then_continues_finalize_without_changing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, gate = _queued(tmp_path)
    job = registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    job = registry.record_stage_progress(job, StageId.METRIC_CANONICALIZE)
    job = registry.record_metric_confirmation(job, _confirmation(registry, job.job_id))
    current = {"vram_free_gb": 100.0, "ram_available_gb": 0.01, "disk_free_gb": 100.0}
    monkeypatch.setattr(admission, "measure_live_headroom", lambda path: current)
    calls: list[str] = []

    def finalize(job_id: str, *, expected_checksum: str) -> JobManifest:
        assert expected_checksum == job.job_manifest_checksum
        calls.append(job_id)
        return registry.record_stage_progress(job, StageId.RGB_GEOMETRY)

    assert not dispatch_next(registry, finalize_runner=finalize, admission=gate)
    wait = resource_wait(gate.database, job)
    progress = job_progress(job, registry.list_job_attempts(job.job_id), True, wait)
    assert progress.waiting_for == "resources" and not calls
    assert progress.stages[-3].state == "succeeded" and progress.stages[-2].state == "pending"
    assert registry.get_job(job.job_id) == job
    current["ram_available_gb"] = 100.0
    assert dispatch_next(registry, finalize_runner=finalize, admission=gate)
    assert calls == [job.job_id] and registry.get_job(job.job_id).config_checksum == job.config_checksum


@pytest.mark.asyncio
async def test_progress_api_reads_durable_wait_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from src.api.studio import deps
    from src.main import app

    registry, job, gate = _queued(tmp_path)
    monkeypatch.setattr(
        admission,
        "measure_live_headroom",
        lambda path: {
            "vram_free_gb": 100.0,
            "ram_available_gb": None,
            "disk_free_gb": 100.0,
        },
    )
    assert not gate(job)
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(deps, "preview_ready", lambda registry, job_id: False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/jobs/{job.job_id}/progress")
    assert response.status_code == 200
    payload = response.json()
    assert payload["waiting_for"] == "resources" and payload["status"] == "QUEUED"
    assert payload["resource_wait"]["job_manifest_checksum"] == job.job_manifest_checksum
    assert payload["resource_wait"]["available_gb"]["ram"] is None


# --- Increment audit: GPU của worker, giữ chỗ, lý do chờ, lỗi của gate, dọn khi thiếu đĩa ---

GPU = GpuReading(index=0, uuid="GPU-shared", name="T2000", total_gb=4.0, free_gb=3.8, used_gb=0.2)
LIVE = {"vram_free_gb": 3.8, "ram_available_gb": 60.0, "disk_free_gb": 400.0}
CAPACITY = {"vram": 4.0, "ram": 64.0, "disk": 500.0}


def _machine(monkeypatch: pytest.MonkeyPatch, live: dict | None = None, capacity: dict | None = None) -> dict:
    """Máy giả lập một GPU 4 GB; trả dict `live` để test đổi số đo giữa các lượt poll."""
    current = dict(live or LIVE)
    monkeypatch.setattr(admission, "measure_live_headroom", lambda path: current)
    monkeypatch.setattr(admission, "measure_capacity", lambda path: capacity or CAPACITY)
    monkeypatch.setattr(admission, "bound_gpu", lambda: GPU)
    return current


def _second_job(registry: ProjectRegistry, suffix: str = "b") -> JobManifest:
    presets, checksum = load_presets(PRESETS)
    config = build_job_config(presets, checksum, preset_values(presets, "minimum_quality"), None)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"), config)
    return _attach_frames(registry, job, _frame_stage(job.job_id, suffix))


def _second_worker(gate: ResourceAdmission, worker_id: str = "same-host:worker-b") -> ResourceAdmission:
    """Worker khác trên cùng máy (cùng DB); PID vẫn là tiến trình test nên được coi là còn sống."""
    other = ResourceAdmission(gate.registry, gate.settings)
    other.worker_id = worker_id
    return other


def _reservations(gate: ResourceAdmission) -> dict[str, admission.Reservation]:
    with gate.database.transaction() as tx:
        rows = tx.execute("SELECT worker_id, payload FROM r2s_resource_reservations").fetchall()
    return {row[0]: admission.Reservation.model_validate_json(row[1]) for row in rows}


def _measure(
    gate: ResourceAdmission, tool: str, vram: float, ram: float, *, params: dict | None = None, **changes: object
) -> None:
    """Ghi một bản ghi đo của lượt chạy trước (cùng GPU, cùng runtime, cấu hình preset tối thiểu)."""
    presets, _ = load_presets(PRESETS)
    now = datetime.now(UTC)
    fields: dict[str, object] = {
        "job_id": "job-earlier",
        "attempt_id": "attempt-earlier",
        "tool": tool,
        "config_checksum": "sha256:" + "c" * 64,
        "runtime_manifest_checksum": gate.registry.get_job("job-fixture-001").runtime_manifest_checksum,
        "params": params or numeric_params(preset_values(presets, "minimum_quality")),
        "gpu_name": GPU.name,
        "shared_gpu": False,
        "started_at": now,
        "completed_at": now,
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
    usage = ResourceUsage(**{**fields, **changes})
    with gate.database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_resource_usage(usage_id,job_id,recorded_at,payload) VALUES (?,?,?,?)",
            (uuid4().hex, usage.job_id, now.isoformat(), usage.model_dump_json()),
        )


def test_unmeasured_job_runs_alone_and_blocks_sharing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chưa có số đo cho cấu hình: job đầu chạy một mình trên GPU, job sau chờ dù VRAM còn trống."""
    registry, first, gate = _queued(tmp_path)
    second = _second_job(registry)
    _machine(monkeypatch)
    other = _second_worker(gate)
    assert gate(first)
    assert _reservations(gate)[gate.worker_id].exclusive
    assert not other(second)
    wait = resource_wait(gate.database, second)
    assert wait is not None and wait.waiting_on == ["vram"] and wait.reasons == {"vram": "busy"}
    assert wait.needs_exclusive_gpu and wait.estimate_scope == "configured_preview"
    assert other.worker_id not in _reservations(gate)
    gate.release()
    assert other(second) and resource_wait(gate.database, second) is None
    assert set(_reservations(gate)) == {other.worker_id}


def test_job_alone_on_gpu_is_not_held_back_by_a_wrong_estimate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ước lượng cao hơn phần trống (hoặc không đo được VRAM) không giữ job chờ vô hạn khi GPU không có job khác."""
    for index, vram in enumerate((0.3, None)):
        registry, job, gate = _queued(tmp_path / str(index))
        _machine(monkeypatch, {**LIVE, "vram_free_gb": vram})
        assert gate(job) and resource_wait(gate.database, job) is None


@pytest.mark.parametrize("phase", ["preview", "finalize"])
def test_heavier_config_measurement_does_not_block_first_exclusive_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: Phase
) -> None:
    """A larger run is an upper bound, not a measurement permitting the new config to share a GPU."""
    registry, job, gate = _queued(tmp_path)
    second = _second_job(registry)
    _machine(monkeypatch, {**LIVE, "vram_free_gb": 3.62})
    presets, _ = load_presets(PRESETS)
    heavier = numeric_params(preset_values(presets, "minimum_quality"))
    heavier["brush.max_splats"] *= 2
    tools = ("preview",) if phase == "preview" else ("finalize", "scene_extract")
    for tool in tools:
        _measure(gate, tool, vram=3.62, ram=3.0, params=heavier)

    assert gate(job, phase=phase)
    assert _reservations(gate)[gate.worker_id].exclusive
    assert resource_wait(gate.database, job) is None
    other = _second_worker(gate)
    assert not other(second, phase=phase)
    wait = resource_wait(gate.database, second)
    assert wait is not None and wait.needs_exclusive_gpu
    assert wait.reasons == {"vram": "busy"}


def test_measured_jobs_share_a_gpu_until_measured_budgets_no_longer_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, first, gate = _queued(tmp_path)
    second, third = _second_job(registry), _second_job(registry, "c")
    _machine(monkeypatch)
    _measure(gate, "preview", vram=1.5, ram=3.0)
    other, another = _second_worker(gate), _second_worker(gate, "same-host:worker-c")
    assert gate(first)
    mine = _reservations(gate)[gate.worker_id]
    assert not mine.exclusive and mine.required_gb == {"vram": 1.5, "ram": 3.0, "disk": 5.96}
    assert other(second)  # 4 GB: hai job 1,5 GB chạy chung được
    assert not another(third)  # job thứ ba: 4 − 3 = 1 GB còn lại < 1,5 GB
    wait = resource_wait(gate.database, third)
    assert wait is not None and wait.estimate_scope == "measured" and not wait.needs_exclusive_gpu
    assert wait.reasons == {"vram": "busy"} and wait.available_gb["vram"] == pytest.approx(1.0)
    other.release()
    assert another(third)


def test_measured_budget_still_respects_what_is_actually_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Số đo nói cần 1,5 GB mà GPU chỉ còn 1 GB (thứ khác chiếm): chờ, vì chạy là tràn."""
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch, {**LIVE, "vram_free_gb": 1.0})
    _measure(gate, "preview", vram=1.5, ram=3.0)
    assert not gate(job)
    assert resource_wait(gate.database, job).reasons == {"vram": "external"}


def test_finalize_needs_measurements_of_both_its_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    _measure(gate, "finalize", vram=0.2, ram=0.8)
    assert gate(job, "finalize") and _reservations(gate)[gate.worker_id].exclusive  # thiếu số đo tách vật thể
    gate.release()
    _measure(gate, "scene_extract", vram=2.3, ram=4.6)
    assert gate(job, "finalize")
    mine = _reservations(gate)[gate.worker_id]
    assert not mine.exclusive and mine.required_gb == {"vram": 2.3, "ram": 4.6, "disk": 5.96}


def test_job_that_ran_out_of_memory_before_reruns_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    _measure(gate, "preview", vram=1.5, ram=3.0)
    _measure(gate, "preview", vram=1.5, ram=3.0, job_id=job.job_id, outcome="failed", exit_code=1, exhausted=True)
    assert gate(job) and _reservations(gate)[gate.worker_id].exclusive


def test_scene_exhaustion_does_not_make_a_pipeline_job_run_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    _measure(gate, "preview", vram=1.5, ram=3.0)
    _measure(
        gate, "scene.geometry", vram=1.5, ram=3.0, job_id=job.job_id, outcome="failed", exit_code=1, exhausted=True
    )
    assert gate(job) and not _reservations(gate)[gate.worker_id].exclusive


def test_reservation_on_another_gpu_of_the_same_host_only_shares_ram_and_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, first, gate = _queued(tmp_path)
    second = _second_job(registry)
    _machine(monkeypatch)
    other = _second_worker(gate)
    assert gate(first)
    monkeypatch.setattr(admission, "bound_gpu", lambda: GpuReading(1, "GPU-other", "T2000", 4.0, 3.8, 0.2))
    assert other(second)  # GPU khác: job chạy một mình trên GPU kia không chặn GPU này


def test_dead_or_stale_reservations_do_not_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    now = datetime.now(UTC)
    held = {"vram": 3.9, "ram": 1.0, "disk": 1.0}
    crashed = admission.Reservation(
        worker_id="crashed", host=gate.host, pid=finished.pid, gpu_uuid=GPU.uuid, job_id="job-x",
        required_gb=held, reserved_at=now, heartbeat_at=now,
    )  # fmt: skip
    silent = crashed.model_copy(
        update={"worker_id": "silent", "host": "other-host", "heartbeat_at": now - timedelta(minutes=16)}
    )
    with gate.database.transaction(write=True) as tx:
        for item in (crashed, silent):
            tx.execute(
                "INSERT INTO r2s_resource_reservations(worker_id,payload) VALUES (?,?)",
                (item.worker_id, item.model_dump_json()),
            )
    assert gate(job)
    assert set(_reservations(gate)) == {gate.worker_id}  # dòng chết bị dọn tại chỗ


@pytest.mark.parametrize(
    ("live", "capacity", "reason"),
    [
        ({**LIVE, "ram_available_gb": 0.5}, CAPACITY, "external"),  # không worker nào giữ chỗ: thứ khác đang chiếm
        ({**LIVE, "ram_available_gb": 0.9}, {**CAPACITY, "ram": 1.0}, "exceeds_machine"),
        ({**LIVE, "ram_available_gb": None}, {**CAPACITY, "ram": None}, "unmeasured"),
    ],
)
def test_wait_reason_tells_whether_waiting_can_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live: dict, capacity: dict, reason: str
) -> None:
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch, live, capacity)
    assert not gate(job)
    wait = resource_wait(gate.database, job)
    assert wait is not None and wait.reasons == {"ram": reason}
    assert registry.get_job(job.job_id) == job  # không lý do nào tự đổi trạng thái job
    progress = job_progress(job, registry.list_job_attempts(job.job_id), False, wait)
    assert progress.resource_wait is not None and progress.resource_wait.reasons == {"ram": reason}


def test_gate_failure_never_changes_job_state_and_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lỗi DB thoáng qua khi ghi observation: job vẫn QUEUED, lượt poll sau chạy bình thường."""
    registry, job, gate = _queued(tmp_path)
    live = _machine(monkeypatch, {**LIVE, "ram_available_gb": 0.01})
    real = gate.database.transaction
    failures = {"left": 1}

    def flaky(*args: object, **kwargs: object) -> object:
        if kwargs.get("write") and failures["left"]:
            failures["left"] -= 1
            raise sqlite3.OperationalError("database is locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(gate.database, "transaction", flaky)

    def unexpected(*args: object, **kwargs: object) -> JobManifest:
        raise AssertionError("gate lỗi không được chạy tool")

    assert not dispatch_next(registry, runner=unexpected, admission=gate)
    assert registry.get_job(job.job_id) == job and registry.get_job(job.job_id).status == JobStatus.QUEUED
    live["ram_available_gb"] = 60.0
    calls: list[str] = []

    def run(job_id: str, uri: str, *, expected_checksum: str) -> JobManifest:
        calls.append(job_id)
        assert set(_reservations(gate)) == {gate.worker_id}  # giữ chỗ suốt lúc job chạy
        return registry.get_job(job_id)

    assert dispatch_next(registry, runner=run, admission=gate) and calls == [job.job_id]
    assert _reservations(gate) == {}  # nhả ngay khi lượt dispatch kết thúc


def test_reservation_released_even_when_runner_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch)

    def interrupted(job_id: str, uri: str, *, expected_checksum: str) -> JobManifest:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        dispatch_next(registry, runner=interrupted, admission=gate)
    assert _reservations(gate) == {}


def test_unreadable_job_config_is_left_for_the_runner_to_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cấu hình hỏng là lỗi của job, không phải thiếu tài nguyên: không được chờ vô hạn."""
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch, {**LIVE, "vram_free_gb": 0.01})
    monkeypatch.setattr(registry.runtime_resolver, "require", Mock(side_effect=admission.ArtifactStoreError("missing")))
    assert gate(job) and resource_wait(gate.database, job) is None
    assert _reservations(gate)[gate.worker_id].required_gb is None


def test_disk_shortage_reclaims_scratch_once_per_interval_then_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services.orchestration.jobs.workspace import CleanupResult
    from src.services.orchestration.projects import deletion

    registry, job, gate = _queued(tmp_path)
    live = _machine(monkeypatch, {**LIVE, "disk_free_gb": 1.0})
    other = _second_worker(gate)
    with gate.database.transaction(write=True) as tx:
        # Worker cùng máy nhưng ở GPU khác: chỉ chia RAM/đĩa với worker này.
        other._reserve(tx, registry.get_job("job-fixture-001"), None, "GPU-other", exclusive=True)
    calls: list[set[str]] = []

    def reclaim(*, worker_root: Path, artifact_root: Path, protected_jobs: set[str]) -> CleanupResult:
        calls.append(set(protected_jobs))
        live["disk_free_gb"] = 400.0 if len(calls) == 1 else live["disk_free_gb"]
        return CleanupResult(files_removed=3, bytes_removed=10)

    purge = Mock(return_value=["entry"])
    monkeypatch.setattr(admission, "reclaim_worker_scratch", reclaim)
    monkeypatch.setattr(deletion, "purge_expired", purge)
    monkeypatch.setattr(deletion, "context_from_settings", lambda settings: "context")
    assert gate(job)  # thiếu đĩa → dọn → đo lại → đủ
    assert calls == [{"job-fixture-001"}] and purge.call_count == 1  # job worker khác đang chạy được bảo vệ
    gate.release()
    live["disk_free_gb"] = 1.0
    assert not gate(job) and len(calls) == 1  # trong khoảng nghỉ: không quét lại mỗi lượt poll
    wait = resource_wait(gate.database, job)
    assert wait is not None and wait.reasons == {"disk": "busy"}
    # Cấu hình cần nhiều hơn cả ổ đĩa: dọn cũng vô ích, không quét.
    gate._last_reclaim = None
    monkeypatch.setattr(admission, "measure_capacity", lambda path: {**CAPACITY, "disk": 2.0})
    assert not gate(job) and len(calls) == 1
    assert resource_wait(gate.database, job).reasons == {"disk": "exceeds_machine"}


def test_machine_idle_and_heartbeat_touch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    monkeypatch.setattr(admission, "process_tree", lambda table, roots: set(roots))  # worker không có tiến trình con
    other = _second_worker(gate)
    assert gate.machine_idle()
    assert gate(job)
    assert not gate.machine_idle() and not other.machine_idle()  # đang giữ chỗ / worker cùng máy đang chạy
    before = _reservations(gate)[gate.worker_id].heartbeat_at
    gate.touch()
    assert _reservations(gate)[gate.worker_id].heartbeat_at > before
    gate.release()
    assert gate.machine_idle()
    monkeypatch.setattr(admission, "process_tree", lambda table, roots: {*roots, 999999})  # đang chạy tool
    assert not gate.machine_idle()


def test_legacy_job_without_estimate_still_marks_machine_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, _, gate = _queued(tmp_path)
    _machine(monkeypatch, {**LIVE, "vram_free_gb": 0.01})
    legacy = registry.get_job("job-fixture-001")
    assert gate(legacy)  # chưa có mô hình ước lượng: không bịa yêu cầu, không chờ
    reservation = _reservations(gate)[gate.worker_id]
    assert reservation.job_id == legacy.job_id and reservation.required_gb is None
    with gate.database.transaction() as tx:
        payload = tx.execute(
            "SELECT payload FROM r2s_resource_reservations WHERE worker_id=?", (gate.worker_id,)
        ).fetchone()[0]
    assert not {
        "gpu_required",
        "operation_kind",
        "operation_id",
        "parent_kind",
        "parent_id",
        "input_checksum",
        "config_checksum",
    } & set(json.loads(payload))


def test_job_reservation_and_touch_job_reservation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    assert gate(job)

    # Tìm reservation qua job_id
    res = admission.job_reservation(gate.database, job.job_id)
    assert res is not None
    assert res.job_id == job.job_id
    old_heartbeat = res.heartbeat_at

    # touch_job_reservation cập nhật heartbeat
    admission.touch_job_reservation(gate.database, job.job_id)
    res_touched = admission.job_reservation(gate.database, job.job_id)
    assert res_touched is not None
    assert res_touched.heartbeat_at > old_heartbeat

    # Job không tồn tại trả None
    assert admission.job_reservation(gate.database, "non-existent-job") is None


def _operation_request(
    *,
    operation_kind: admission.OperationKind = "reobjectify",
    operation_id: str = "operation-objectify-001",
    parent_id: str = "job-fixture-001",
    required_gb: dict[str, float | None] | None = None,
    gpu_required: bool = True,
    measured: bool = True,
    requested_gpu_uuid: str | None = None,
    input_checksum: str = "sha256:" + "a" * 64,
    config_checksum: str = "sha256:" + "b" * 64,
) -> admission.OperationAdmissionRequest:
    return admission.OperationAdmissionRequest(
        operation_kind=operation_kind,
        operation_id=operation_id,
        parent_kind="job",
        parent_id=parent_id,
        input_checksum=input_checksum,
        config_checksum=config_checksum,
        resources=admission.OperationResourceProfile(
            required_gb=required_gb or {"vram": 1.0, "ram": 2.0, "disk": 2.0},
            danger_ratio=0.9,
            measured=measured,
            gpu_required=gpu_required,
        ),
        requested_gpu_uuid=requested_gpu_uuid,
    )


def test_operation_and_job_share_one_admission_reservation_without_fake_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    operation_worker = _second_worker(gate, "same-host:operation-worker")
    request = _operation_request(requested_gpu_uuid=GPU.uuid, parent_id=job.job_id)

    admitted = operation_worker.admit_operation(request)
    assert admitted.status == "admitted"
    assert admitted.request == request and admitted.waiting_on == []
    reservation = _reservations(gate)[operation_worker.worker_id]
    assert reservation.job_id is None
    assert reservation.operation_id == request.operation_id
    assert reservation.input_checksum == request.input_checksum
    assert reservation.config_checksum == request.config_checksum

    # The legacy job adapter cannot replace an operation's reservation in the same worker.
    assert not operation_worker(job)
    assert _reservations(gate)[operation_worker.worker_id] == reservation
    # A second worker sees the same GPU reservation and keeps the job/config queued.
    assert not gate(job)
    wait = resource_wait(gate.database, job)
    assert wait is not None and wait.waiting_on == ["vram"] and wait.reasons == {"vram": "busy"}
    assert operation_worker.release_operation(request)
    assert gate(job)


def test_duplicate_operation_admission_is_fenced_and_release_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, gate = _queued(tmp_path)
    _machine(monkeypatch)
    request = _operation_request()
    assert gate.admit_operation(request).status == "admitted"
    assert gate.admit_operation(request).status == "worker_busy"
    other_worker = _second_worker(gate, "same-host:duplicate-operation-worker")
    assert other_worker.admit_operation(request).status == "worker_busy"
    changed_input = _operation_request(input_checksum="sha256:" + "c" * 64)
    assert gate.admit_operation(changed_input).status == "identity_conflict"
    assert not gate.release_operation(changed_input)
    assert gate.release_operation(request)
    assert gate.release_operation(request)
    assert _reservations(gate) == {}


def test_import_profile_scales_with_gaussian_count_and_marks_heuristic(tmp_path: Path) -> None:
    _, _, gate = _queued(tmp_path)

    gpu_profile = gate.operation_profile_for_import(
        gaussian_count=1_000_000,
        source_size_bytes=1_000_000_000,
        gpu_required=True,
    )
    # Cập nhật kỳ vọng theo hệ số đã hiệu chuẩn (vram_base_gb 1.25, ram_base_gb 0.9, AUD-26.S1)
    assert gpu_profile.required_gb == {"vram": 2.35, "ram": 2.15, "disk": 2.0}
    assert gpu_profile.danger_ratio == 0.92 and gpu_profile.measured is False and gpu_profile.gpu_required

    cpu_profile = gate.operation_profile_for_import(
        gaussian_count=1_000_000,
        source_size_bytes=1_000_000_000,
        gpu_required=False,
    )
    assert cpu_profile.required_gb["vram"] == 0.0 and not cpu_profile.gpu_required


def test_expired_operation_lease_cannot_touch_or_release_new_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, gate = _queued(tmp_path)
    _machine(monkeypatch)
    old = _operation_request().model_copy(update={"lease_token": "old-lease", "lease_generation": 1})
    current = _operation_request().model_copy(update={"lease_token": "new-lease", "lease_generation": 2})

    assert gate.admit_operation(old).status == "admitted"
    assert gate.release_operation(old)
    assert gate.admit_operation(current).status == "admitted"
    assert not gate.touch_operation(old)
    assert not gate.release_operation(old)
    reservations = _reservations(gate)
    assert len(reservations) == 1
    assert next(iter(reservations.values())).lease_token == "new-lease"
    assert gate.release_operation(current)


def test_operation_waits_when_requested_gpu_affinity_does_not_match_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, gate = _queued(tmp_path)
    _machine(monkeypatch)
    request = _operation_request(requested_gpu_uuid="GPU-requested")
    result = gate.admit_operation(request)
    assert result.status == "waiting_gpu_affinity"
    assert result.bound_gpu_uuid == GPU.uuid
    assert result.request.requested_gpu_uuid == "GPU-requested"
    assert _reservations(gate) == {}


def test_operation_kind_requires_matching_parent_identity() -> None:
    payload = _operation_request().model_dump()
    payload.update(operation_kind="import_package", parent_kind="job")
    with pytest.raises(ValidationError, match="must bind an import parent"):
        admission.OperationAdmissionRequest.model_validate(payload)

    payload = _operation_request(operation_kind="rgb_lidar_register").model_dump()
    payload.update(parent_kind="import")
    with pytest.raises(ValidationError, match="must bind a job parent"):
        admission.OperationAdmissionRequest.model_validate(payload)


def test_rgb_lidar_registration_uses_shared_cpu_operation_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    worker = _second_worker(gate, "same-host:registration-worker")
    request = _operation_request(
        operation_kind="rgb_lidar_register",
        parent_id=job.job_id,
        required_gb={"vram": 0.0, "ram": 1.0, "disk": 1.0},
        gpu_required=False,
        input_checksum="sha256:" + "d" * 64,
        config_checksum="sha256:" + "e" * 64,
    )

    admitted = worker.admit_operation(request)

    assert admitted.status == "admitted"
    assert admitted.request == request
    reservation = _reservations(gate)[worker.worker_id]
    assert reservation.operation_id == request.operation_id
    assert reservation.job_id is None
    assert reservation.input_checksum == request.input_checksum
    assert reservation.config_checksum == request.config_checksum
    assert worker.release_operation(request)


@pytest.mark.parametrize(
    ("resource", "need", "free", "capacity", "reason"),
    [
        ("vram", None, 3.8, 4.0, "unmeasured"),
        ("ram", None, 60.0, 64.0, "unmeasured"),
        ("disk", None, 400.0, 500.0, "unmeasured"),
        ("vram", 4.0, 3.8, 4.0, "exceeds_machine"),
        ("ram", 65.0, 60.0, 64.0, "exceeds_machine"),
        ("disk", 501.0, 400.0, 500.0, "exceeds_machine"),
    ],
)
def test_operation_unknown_or_impossible_resource_never_admits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    need: float | None,
    free: float | None,
    capacity: float | None,
    reason: str,
) -> None:
    _, _, gate = _queued(tmp_path)
    headroom_field = {"vram": "vram_free_gb", "ram": "ram_available_gb", "disk": "disk_free_gb"}[resource]
    live = {**LIVE, headroom_field: free}
    totals = {**CAPACITY, resource: capacity}
    _machine(monkeypatch, live, totals)
    values: dict[str, float | None] = {"vram": 1.0, "ram": 2.0, "disk": 2.0}
    values[resource] = need
    request = _operation_request(required_gb=values)

    result = gate.admit_operation(request)
    assert result.status == "waiting_resources"
    assert result.waiting_on == [resource]
    assert result.reasons == {resource: reason}
    assert result.request.input_checksum == request.input_checksum
    assert result.request.config_checksum == request.config_checksum
    assert _reservations(gate) == {}


@pytest.mark.parametrize(
    ("resource", "free"),
    [("vram", None), ("ram", None), ("disk", None)],
)
def test_operation_waits_when_live_headroom_is_unmeasured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    free: float | None,
) -> None:
    _, _, gate = _queued(tmp_path)
    headroom_field = {"vram": "vram_free_gb", "ram": "ram_available_gb", "disk": "disk_free_gb"}[resource]
    _machine(monkeypatch, {**LIVE, headroom_field: free})
    result = gate.admit_operation(_operation_request())
    assert result.status == "waiting_resources"
    assert result.waiting_on == [resource]
    assert result.reasons == {resource: "unmeasured"}
    assert _reservations(gate) == {}


def test_cpu_only_operation_does_not_require_or_reserve_gpu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, job, gate = _queued(tmp_path)
    cpu_worker = _second_worker(gate, "same-host:cpu-operation-worker")
    _machine(monkeypatch, {"vram_free_gb": None, "ram_available_gb": 60.0, "disk_free_gb": 400.0})
    monkeypatch.setattr(admission, "bound_gpu", lambda: None)
    request = _operation_request(
        required_gb={"vram": None, "ram": 2.0, "disk": 2.0},
        gpu_required=False,
    )
    assert cpu_worker.admit_operation(request).status == "admitted"
    reservation = _reservations(gate)[cpu_worker.worker_id]
    assert not reservation.gpu_required and reservation.gpu_uuid is None

    # CPU work consumes RAM/disk, but it does not block a GPU-only job on VRAM.
    monkeypatch.setattr(admission, "bound_gpu", lambda: GPU)
    assert gate(job)
    assert {item.worker_id for item in _reservations(gate).values()} == {gate.worker_id, cpu_worker.worker_id}


def test_disk_reclaim_protects_job_owned_by_an_operation_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services.orchestration.jobs.workspace import CleanupResult
    from src.services.orchestration.projects import deletion

    _, job, gate = _queued(tmp_path)
    _machine(monkeypatch)
    operation_worker = _second_worker(gate, "same-host:operation-worker")
    request = _operation_request(parent_id=job.job_id)
    assert operation_worker.admit_operation(request).status == "admitted"
    captured: list[set[str]] = []

    def capture_reclaim(*, worker_root: Path, artifact_root: Path, protected_jobs: set[str]) -> CleanupResult:
        captured.append(set(protected_jobs))
        return CleanupResult(files_removed=0, bytes_removed=0)

    monkeypatch.setattr(admission, "reclaim_worker_scratch", capture_reclaim)
    monkeypatch.setattr(deletion, "purge_expired", lambda context: [])
    monkeypatch.setattr(deletion, "context_from_settings", lambda settings: "context")
    assert gate._reclaim_disk(job)
    assert captured == [{job.job_id}]


def test_old_job_reservation_payload_remains_readable_without_schema_migration() -> None:
    now = datetime.now(UTC)
    old_payload = {
        "worker_id": "old-worker",
        "host": "worker-host",
        "pid": 123,
        "gpu_uuid": "GPU-old",
        "job_id": "job-old",
        "required_gb": {"vram": 1.0, "ram": 2.0, "disk": 3.0},
        "exclusive": False,
        "phase": "preview",
        "reserved_at": now.isoformat(),
        "heartbeat_at": now.isoformat(),
    }
    reservation = admission.Reservation.model_validate_json(json.dumps(old_payload))
    assert reservation.job_id == "job-old"
    assert reservation.operation_id is None and reservation.gpu_required


def test_restarted_worker_with_same_identity_discards_its_leftover_operation_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Container restarts reuse host:pid; a killed objectify must not block the new process forever."""
    _, job, crashed = _queued(tmp_path)
    _machine(monkeypatch)
    assert crashed.admit_operation(_operation_request(operation_id="operation-before-crash")).status == "admitted"
    other = _second_worker(crashed, "same-host:other-live-worker")
    small = _operation_request(operation_id="operation-other", required_gb={"vram": 0.1, "ram": 1.0, "disk": 1.0})
    assert other.admit_operation(small).status == "admitted"

    restarted = _second_worker(crashed, crashed.worker_id)
    retry = _operation_request(operation_id="operation-after-restart")
    assert restarted.admit_operation(retry).status == "worker_busy"
    assert not restarted(job)

    assert restarted.discard_leftover_reservation()
    assert not restarted.discard_leftover_reservation()
    assert set(_reservations(crashed)) == {other.worker_id}
    assert restarted.admit_operation(retry).status == "admitted"
