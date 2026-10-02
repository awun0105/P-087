"""Durable queue fixture proof: chờ/tiếp tục/cancel giữ config và provenance."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.config import Settings
from src.models.contracts.manifests import JobManifest, JobStatus, StageId
from src.services.orchestration.jobs import admission
from src.services.orchestration.jobs.admission import ResourceAdmission, resource_wait
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.progress import job_progress
from src.services.orchestration.jobs.worker_cli import dispatch_next
from src.services.orchestration.processing import build_job_config, job_config_reference, load_presets, preset_values
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
        lambda path: {"vram_free_gb": free, "ram_available_gb": 100.0, "disk_free_gb": 100.0},
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
    assert wait is not None and wait.waiting_on == ["vram"]
    progress = job_progress(job, events, False, wait)
    assert progress.waiting_for == "resources" and progress.status == "QUEUED"
    assert all(stage.state == "pending" for stage in progress.stages if stage.stage_id != "ST-FRAME-EXTRACT")


def test_resource_recovery_automatically_dispatches_same_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, job, gate = _queued(tmp_path)
    current = {"vram_free_gb": 0.01, "ram_available_gb": 100.0, "disk_free_gb": 100.0}
    monkeypatch.setattr(admission, "measure_live_headroom", lambda path: current)
    assert not dispatch_next(registry, admission=gate)
    calls: list[str] = []

    def run(job_id: str, uri: str, *, expected_checksum: str) -> JobManifest:
        calls.append(job_id)
        assert expected_checksum == job.job_manifest_checksum
        return registry.transition_job(
            job_id, TransitionRequest(target_status=JobStatus.RUNNING), expected_checksum=expected_checksum
        )

    current["vram_free_gb"] = 100.0
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
        lambda path: {"vram_free_gb": 0.01, "ram_available_gb": 100.0, "disk_free_gb": 100.0},
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
    current = {"vram_free_gb": 0.01, "ram_available_gb": 100.0, "disk_free_gb": 100.0}
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
    current["vram_free_gb"] = 100.0
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
            "vram_free_gb": None,
            "ram_available_gb": 100.0,
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
    assert payload["resource_wait"]["available_gb"]["vram"] is None
