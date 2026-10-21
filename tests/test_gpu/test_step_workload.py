"""T-073: bộ thuê máy đếm nhu cầu theo bước sẵn sàng của từng job, không theo số job."""

from pathlib import Path

import pytest

from src.models.contracts.manifests import StageId
from src.services.orchestration.gpu.catalog import ReleaseCatalog, ReleaseProfile
from src.services.orchestration.gpu.status import gpu_capacity
from src.services.orchestration.gpu.workload import scan_scope
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.steps import enqueue_view_lod
from src.services.orchestration.projects.models import JobCreateInput
from tests.test_orchestration.test_anonymization_review import _after_prepare
from tests.test_orchestration.test_prepared_queue import _registry
from tests.test_orchestration.test_step_queue import _geometry_done, _prepared


def _catalog(registry) -> ReleaseCatalog:  # noqa: ANN001
    profile = ReleaseProfile(
        name="native",
        image="registry/worker@sha256:" + "1" * 64,
        execution=ExecutionProfile(
            config_checksum=registry.execution_profile.config_checksum,
            runtime_manifest_checksum=registry.execution_profile.runtime_manifest_checksum,
            seed=7,
        ),
        kinds={"pipeline", "scene", "validation", "import"},
        gpu_types=("qualified-gpu",),
        cuda_versions=("12.6",),
        min_vram_gb=24,
        min_ram_gb=32,
        min_cpus=4,
        scratch_gb=50,
        qualification_reference="fixture-only",
        storage_hourly_usd=0.01,
    )
    return ReleaseCatalog(profiles=(profile,), checksum="fixture")


def test_cpu_and_gpu_steps_both_rent_a_gpu_pod_but_user_waits_do_not(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "a")
    registry.create_job(JobCreateInput(project_id="project-fixture-001"))  # bước chuẩn bị (CPU)
    _prepared(registry)  # bước dựng camera (GPU)
    assert registry.persistence is not None
    work = scan_scope(registry.persistence.database, registry, _catalog(registry))
    assert (work.cpu_steps, work.gpu_steps) == (1, 1)
    # Chủ dự án chốt: làn CPU trên máy API không nhận bước pipeline, nên bước CPU cũng là nhu cầu thuê máy GPU.
    assert len(work.pending) == 2 and {item.kind for item in work.pending} == {"pipeline"}
    assert work.cpu_pending == 0


def test_job_waiting_for_the_user_and_background_lod_rent_nothing(tmp_path: Path) -> None:
    registry, _ = _after_prepare(tmp_path / "review")  # chờ người dùng duyệt bản đã che
    assert registry.persistence is not None
    work = scan_scope(registry.persistence.database, registry, _catalog(registry))
    assert work.pending == [] and (work.cpu_steps, work.gpu_steps) == (0, 0)

    registry, job = _geometry_done(tmp_path / "lod")
    done = registry.record_scene_extract(registry.record_stage_progress(job, StageId.OBJECT_EXTRACT), [])
    assert registry.persistence is not None
    enqueue_view_lod(registry.persistence.database, done)
    work = scan_scope(registry.persistence.database, registry, _catalog(registry))
    assert work.pending == []


def test_scene_step_after_geometry_is_gpu_demand(tmp_path: Path) -> None:
    registry, _ = _geometry_done(tmp_path)
    assert registry.persistence is not None
    work = scan_scope(registry.persistence.database, registry, _catalog(registry))
    assert (work.cpu_steps, work.gpu_steps) == (0, 1) and len(work.pending) == 1


@pytest.mark.parametrize("deployment", ["", "test"])
def test_gpu_status_reports_waiting_steps_by_kind(tmp_path: Path, deployment: str) -> None:
    registry = _registry(tmp_path)
    registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    _prepared(registry)
    _prepared(registry)
    assert registry.persistence is not None
    capacity = gpu_capacity(registry.persistence.database, deployment)
    assert (capacity.pending_gpu_steps, capacity.pending_cpu_steps) == (2, 1)
