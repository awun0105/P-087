"""Lifecycle acceptance with a stateful provider, injected queues and durable DB."""

import json
from pathlib import Path

import pytest

from src.services.orchestration.gpu.catalog import ReleaseCatalog, ReleaseProfile, load_catalog, seal
from src.services.orchestration.gpu.config import GpuSettings
from src.services.orchestration.gpu.controller import Controller
from src.services.orchestration.gpu.provider import ProviderError, Quote, RunPod
from src.services.orchestration.gpu.state import StateStore, claim_allowed
from src.services.orchestration.gpu.workload import Demand, Workload, import_gpu, scene_gpu
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile


@pytest.fixture
def profile():
    return ReleaseProfile(
        name="native",
        image="registry/worker@sha256:" + "1" * 64,
        execution=ExecutionProfile(
            config_checksum="sha256:" + "2" * 64, runtime_manifest_checksum="sha256:" + "3" * 64
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


class FakeRunPod:
    def __init__(self):
        self.pods, self.creates, self.deletes = [], 0, []
        self.create_error = None
        self.list_error = None
        self.offers = [Quote("qualified-gpu", 0.5, 24)]

    def list(self):
        if self.list_error:
            raise self.list_error
        return self.pods.copy()

    def get(self, pod_id):
        return next((p for p in self.pods if p["id"] == pod_id), None)

    def quotes(self, *args):
        return self.offers

    def create(self, body):
        self.creates += 1
        pod = {
            **body,
            "id": "pod-1",
            "image": body["imageName"],
            "costPerHr": "0.5",
            "gpu": {"count": 1},
            "machine": {"gpuTypeId": "qualified-gpu"},
            "memoryInGb": 32,
            "vcpuCount": 4,
            "desiredStatus": "RUNNING",
        }
        self.pods.append(pod)
        if self.create_error:
            raise self.create_error
        return pod

    def terminate(self, pod_id):
        self.deletes.append(pod_id)
        self.pods = [p for p in self.pods if p["id"] != pod_id]


@pytest.fixture
def world(tmp_path, profile):
    db = RuntimeDatabase(f"sqlite:///{tmp_path / 'state.db'}")
    env = tmp_path / "worker.env"
    env.write_text("DATABASE_URL=postgresql://fixture\nARTIFACT_S3_BUCKET=fixture\nRUNPOD_API_KEY=must-not-forward\n")
    policy = GpuSettings(
        autoprov_enabled=True,
        autoprov_dry_run=False,
        deployment_id="test",
        release_catalog=tmp_path / "catalog.json",
        worker_env_file=env,
        runpod_api_key="fixture",
        max_hourly_usd=1,
        project_budget_usd=10,
        outage_policy="operator_accepted",
        outage_policy_reference="test only",
        idle_seconds=1,
    )
    catalog = ReleaseCatalog(profiles=(profile,), checksum="fixture")
    store, provider = StateStore(db, "test"), FakeRunPod()
    work = Workload(pending=[Demand("main", "pipeline", "job", ("native",))])
    controller = Controller(store, policy, catalog, provider, lambda: work)
    return controller, store, provider, work


def boot(world):
    controller, store, provider, work = world
    assert controller.tick() == "created"
    with store.locked() as (_, c, now):
        c.workers["worker"] = {"ready": True, "busy": False, "heartbeat": now}
    assert controller.tick() == "ready"
    return controller, store, provider, work


def expire_idle(store):
    with store.locked() as (_, c, now):
        c.idle_since = now - 10


def test_empty_queue_creates_nothing(world):
    controller, _, provider, work = world
    work.pending.clear()
    assert controller.tick() == "no_work"
    assert provider.creates == 0


def test_first_job_and_many_jobs_create_one_pod(world):
    controller, store, provider, work = boot(world)
    work.pending *= 10
    assert controller.tick() == "ready"
    assert provider.creates == 1
    assert "RUNPOD_API_KEY" not in provider.pods[0]["env"]
    assert provider.pods[0]["volumeInGb"] == 0
    assert "networkVolumeId" not in provider.pods[0]


def test_full_idle_cycle_and_reprovision(world):
    controller, store, provider, work = boot(world)
    work.pending.clear()
    assert controller.tick() == "idle"
    expire_idle(store)
    assert controller.tick() == "draining"
    assert controller.tick() == "drained"
    assert controller.tick() == "terminating"
    assert controller.tick() == "terminated_confirmed"
    work.pending.append(Demand("main", "pipeline", "next", ("native",)))
    assert controller.tick() == "created"
    assert provider.creates == 2


@pytest.mark.parametrize("reason", ["cpu_phase", "publication", "demo", "validation", "registration", "import"])
def test_active_work_never_terminated(world, reason):
    controller, store, provider, work = boot(world)
    work.pending.clear()
    work.active = 1
    expire_idle(store)
    assert controller.tick() == "busy"
    assert provider.deletes == []


@pytest.mark.parametrize("at_drain", [False, True])
def test_new_work_cancels_shutdown(world, at_drain):
    controller, store, provider, work = boot(world)
    work.pending.clear()
    controller.tick()
    if at_drain:
        expire_idle(store)
        assert controller.tick() == "draining"
    work.pending.append(Demand("main", "scene", "request", ("native",)))
    assert controller.tick() == ("drain_cancelled" if at_drain else "ready")
    assert not provider.deletes


def test_unknown_create_response_is_adopted_without_second_post(world):
    controller, store, provider, work = world
    provider.create_error = ProviderError("timeout", ambiguous=True)
    assert controller.tick() == "provider_error"
    assert provider.creates == 1
    other = Controller(store, controller.policy, controller.catalog, provider, lambda: work)
    with store.locked() as (_, c, now):
        c.leader_until = now - 1
        c.retry_at = 0
    assert other.tick() == "starting"
    assert store.read().pod == "pod-1"
    assert provider.creates == 1


def test_missing_create_response_and_empty_list_do_not_repeat_post(world):
    controller, store, provider, work = world
    provider.create_error = ProviderError("timeout", ambiguous=True)
    controller.tick()
    provider.pods.clear()
    with store.locked() as (_, c, _):
        c.retry_at = 0
    for _ in range(5):
        assert controller.tick() == "reconcile_unknown"
    assert provider.creates == 1


def test_follower_cannot_provision(world):
    controller, store, provider, work = world
    controller.tick()
    other = Controller(store, controller.policy, controller.catalog, provider, lambda: work)
    assert other.tick() == "follower"
    assert provider.creates == 1


def test_incomplete_scan_and_provider_failure_keep_pod(world):
    controller, store, provider, work = boot(world)
    work.pending.clear()
    work.complete = False
    assert controller.tick() == "scan_unknown"
    work.complete = True
    provider.list_error = ProviderError("rate_limit", retry_after=40)
    assert controller.tick() == "provider_error"
    assert controller.tick() == "backoff"
    assert not provider.deletes


def test_budget_disable_and_dry_run(world):
    controller, store, provider, work = world
    controller.policy = controller.policy.model_copy(update={"project_budget_usd": 0.001})
    assert controller.tick() == "budget_blocked"
    controller.policy = controller.policy.model_copy(update={"autoprov_enabled": False})
    assert controller.tick() == "no_work"
    controller.policy = controller.policy.model_copy(
        update={"autoprov_enabled": True, "project_budget_usd": 10, "autoprov_dry_run": True}
    )
    assert controller.tick() == "would_create"
    assert not provider.creates


def test_unavailable_inventory_is_bounded(world):
    controller, store, provider, work = world
    provider.offers.clear()
    for _ in range(3):
        assert controller.tick() == "inventory_blocked"
        with store.locked() as (_, c, _):
            c.retry_at = 0
    assert controller.tick() == "no_work"
    assert store.read().drain
    assert not provider.creates


def test_ownership_mismatch_never_deletes(world):
    controller, store, provider, work = boot(world)
    provider.pods[0]["env"]["GPU_BOOT_TOKEN"] = "unrelated"
    work.pending.clear()
    assert controller.tick() == "blocked"
    assert store.read().error == "ownership_mismatch"
    assert not provider.deletes


def test_claim_gate_fences_retired_generation(world, monkeypatch):
    controller, store, provider, work = boot(world)
    c = store.read()
    monkeypatch.setenv("GPU_DEPLOYMENT_ID", "test")
    monkeypatch.setenv("GPU_BOOT_TOKEN", c.boot_token)
    with store.database.transaction(write=True) as tx:
        assert claim_allowed(tx)
    with store.locked() as (_, c, _):
        c.state = "draining"
    with store.database.transaction(write=True) as tx:
        assert not claim_allowed(tx)
    monkeypatch.setenv("GPU_BOOT_TOKEN", "stale")
    with store.database.transaction(write=True) as tx:
        assert not claim_allowed(tx)


def test_live_configuration_requires_explicit_cost_and_outage_policy():
    with pytest.raises(ValueError):
        GpuSettings(autoprov_enabled=True)
    with pytest.raises(ValueError, match="outage"):
        GpuSettings(
            autoprov_enabled=True,
            autoprov_dry_run=False,
            deployment_id="test",
            release_catalog=Path("x"),
            worker_env_file=Path("y"),
            runpod_api_key="fixture",
            max_hourly_usd=1,
            project_budget_usd=1,
        )


def test_catalog_integrity_and_software_compatibility(tmp_path, profile):
    path = tmp_path / "catalog.json"
    data = seal({"profiles": [profile.model_dump(mode="json")]})
    path.write_text(json.dumps(data))
    catalog = load_catalog(path)
    assert catalog.compatible("pipeline", profile.execution.job_runtime_checksum)
    data["profiles"][0]["min_ram_gb"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        load_catalog(path)


def test_cpu_gpu_classifiers():
    assert not import_gpu("sog", 0)
    assert not import_gpu("ply", None)
    assert import_gpu("ply", 0)
    assert not scene_gpu("boxes", False)
    assert scene_gpu("geometry", False)


def test_rest_adapter_contracts_and_invalid_list():
    calls = []

    def call(method, path, body):
        calls.append((method, path, body))
        return [] if method == "GET" and path.startswith("/pods?") else {"id": "one"}

    provider = RunPod(call)
    assert provider.list() == []
    assert provider.create({"env": {}})["id"] == "one"
    provider.start("one")
    provider.stop("one")
    provider.terminate("one")
    assert [(m, p) for m, p, _ in calls[1:]] == [
        ("POST", "/pods"),
        ("POST", "/pods/one/start"),
        ("POST", "/pods/one/stop"),
        ("DELETE", "/pods/one"),
    ]
    with pytest.raises(ProviderError):
        RunPod(lambda *_: {"partial": []}).list()


def test_job_stays_protected_beyond_soft_lifetime_and_budget(world):
    controller, store, provider, work = boot(world)
    with store.locked() as (_, c, now):
        c.created_at = now - 100000
    work.active = 1
    assert controller.tick() == "busy"
    assert store.read().state == "draining"
    assert provider.deletes == []
    work.active = 0
    assert controller.tick() == "drained"


def test_worker_crash_without_active_leases_is_cleaned_up(world):
    controller, store, provider, work = boot(world)
    with store.locked() as (_, c, now):
        c.workers["worker"]["heartbeat"] = now - 1000
    assert controller.tick() == "draining"
    assert controller.tick() == "drained"
    assert controller.tick() == "terminating"
    assert provider.deletes == ["pod-1"]


def test_valid_lease_keeps_pod_after_worker_heartbeat_lost(world):
    controller, store, provider, work = boot(world)
    with store.locked() as (_, c, now):
        c.workers["worker"]["heartbeat"] = now - 1000
    work.active = 1
    assert controller.tick() == "busy"
    assert not provider.deletes


def test_startup_failure_has_a_deadline_and_bounded_replacements(world):
    controller, store, provider, work = world
    controller.tick()
    for attempt in range(3):
        with store.locked() as (_, c, now):
            c.created_at = now - 1300
        assert controller.tick() == "draining"
        assert controller.tick() == "drained"
        assert controller.tick() == "terminating"
        assert controller.tick() == "terminated_confirmed"
        if attempt < 2:
            assert controller.tick() == "created"
    assert controller.tick() == "blocked"
    assert provider.creates == 3


def test_disabled_provisioning_still_cleans_existing_pod(world):
    controller, store, provider, work = boot(world)
    controller.policy = controller.policy.model_copy(update={"autoprov_enabled": False})
    assert controller.tick() == "draining"
    assert controller.tick() == "drained"
    assert controller.tick() == "terminating"
    assert provider.deletes


def test_starting_pod_does_not_open_claims_due_to_unrelated_cpu_activity(world):
    controller, store, provider, work = world
    assert controller.tick() == "created"
    work.active = 1
    assert controller.tick() == "starting"
    assert store.read().state == "starting"


def test_duplicate_owned_pods_block_automatic_actions(world):
    controller, store, provider, work = boot(world)
    provider.pods.append({**provider.pods[0], "id": "second"})
    assert controller.tick() == "blocked"
    assert not provider.deletes
    assert provider.creates == 1


def test_overpriced_allocation_never_becomes_ready(world):
    controller, store, provider, work = world
    controller.tick()
    provider.pods[0]["costPerHr"] = "9"
    with store.locked() as (_, c, now):
        c.workers["worker"] = {"heartbeat": now, "ready": True, "busy": False}
    assert controller.tick() == "draining"
    assert store.read().state != "ready"


def test_cpu_worker_cannot_claim_pipeline_or_validation(world, monkeypatch):
    _, store, _, _ = world
    monkeypatch.setenv("GPU_CPU_LANE", "true")
    monkeypatch.setenv("GPU_MANAGED_CLAIMS_REQUIRED", "true")
    monkeypatch.delenv("GPU_BOOT_TOKEN", raising=False)
    with store.database.transaction(write=True) as tx:
        assert claim_allowed(tx, "registration")
        assert not claim_allowed(tx, "validation")
        assert not claim_allowed(tx, "pipeline")


def test_quote_response_and_auth_error_sanitization(monkeypatch):
    from urllib.error import HTTPError

    from src.services.orchestration.gpu.provider import transport

    provider = RunPod(
        lambda *_: {
            "data": {
                "gpuTypes": [
                    {
                        "id": "qualified-gpu",
                        "memoryInGb": 24,
                        "lowestPrice": {"uninterruptablePrice": 0.5, "stockStatus": "High", "availableGpuCounts": [1]},
                    }
                ]
            }
        }
    )
    assert provider.quotes(("qualified-gpu",), True) == [Quote("qualified-gpu", 0.5, 24)]

    def fail(*args, **kwargs):
        raise HTTPError("https://fixture", 401, "secret-body", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ProviderError) as error:
        transport("secret-key")("POST", "/pods", {"env": {"secret": "value"}})
    assert str(error.value) == "auth"
    assert error.value.ambiguous


def test_cold_api_can_create_job_without_previous_worker(tmp_path, profile, monkeypatch):
    from src.config import get_settings
    from src.services.orchestration.projects.models import JobCreateInput
    from tests.test_orchestration.test_worker_runtime_selection import _worker_registry

    registry = _worker_registry(tmp_path)
    release = profile.model_copy(
        update={
            "execution": profile.execution.model_copy(
                update={
                    "config_checksum": registry.processing_config_checksum,
                    "seed": 7,
                }
            )
        }
    )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(seal({"profiles": [release.model_dump(mode="json")]})))
    monkeypatch.setenv("PRODUCT_GPU_RELEASE_CATALOG", str(path))
    get_settings.cache_clear()
    try:
        assert registry.job_profile() == release.execution
        job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
        assert job.runtime_manifest_checksum == release.execution.job_runtime_checksum
        assert job.status.value == "QUEUED"
    finally:
        get_settings.cache_clear()


def test_scanner_keeps_active_publication_reservation_and_staged_runtime(tmp_path, profile, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from src.services.orchestration.gpu import workload

    db = RuntimeDatabase(f"sqlite:///{tmp_path / 'queues.db'}")
    monkeypatch.setattr(workload, "waiting_jobs", lambda _: [SimpleNamespace(job_id="staged")])
    registry = SimpleNamespace(
        get_job=lambda _: SimpleNamespace(
            runtime_manifest_checksum=profile.execution.job_runtime_checksum, stage_artifacts=["completed-stage"]
        )
    )
    with db.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_resource_reservations VALUES (?,?)",
            (
                "publisher",
                json.dumps(
                    {"heartbeat_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(), "gpu_required": False}
                ),
            ),
        )
    result = workload.scan_scope(db, registry, ReleaseCatalog(profiles=(profile,), checksum="fixture"))
    assert result.active == 1  # use the existing 15-minute reservation TTL, not a shorter controller TTL
    assert result.pending[0].profiles == ("native",)


def test_scanner_cpu_queue_does_not_create_gpu_demand(tmp_path, profile, monkeypatch):
    from types import SimpleNamespace

    from src.services.orchestration.gpu import workload

    db = RuntimeDatabase(f"sqlite:///{tmp_path / 'queues.db'}")
    monkeypatch.setattr(workload, "waiting_jobs", lambda _: [])
    with db.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_scene_requests VALUES (?,?,?)",
            ("box", "queued", json.dumps({"status": "queued", "mode": "boxes"})),
        )
    result = workload.scan_scope(
        db, SimpleNamespace(), ReleaseCatalog(profiles=(profile,), checksum="fixture"), boxes_gpu=False
    )
    assert result.cpu_pending == 1 and not result.pending


def test_input_registry_available_from_release_at_gpu_zero(tmp_path, profile, monkeypatch):
    from src.config import get_settings
    from src.models.contracts.input_assembly import seal_runtime_registry
    from src.services.orchestration.inputs.assembly import InputAssemblyService

    registry = seal_runtime_registry(
        {
            "schema_version": "1.0",
            "registry_version": "release",
            "capabilities": [],
            "registry_checksum": "sha256:" + "0" * 64,
        }
    )
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            seal({"profiles": [profile.model_dump(mode="json")], "input_registry": registry.model_dump(mode="json")})
        )
    )
    monkeypatch.setenv("PRODUCT_GPU_RELEASE_CATALOG", str(path))
    get_settings.cache_clear()
    try:
        service = InputAssemblyService(RuntimeDatabase(f"sqlite:///{tmp_path / 'inputs.db'}"))
        assert service.runtime_registry().registry_version == "release"
    finally:
        get_settings.cache_clear()


def test_busy_marker_survives_lease_release_until_publication_returns(world, monkeypatch):
    from threading import Event

    from src.services.orchestration.gpu.worker import ManagedWorker
    from src.services.orchestration.jobs.lease import acquire, release

    controller, store, provider, work = boot(world)
    worker = ManagedWorker.__new__(ManagedWorker)
    worker.store, worker.key, worker.token, worker.stop = store, "worker", store.read().boot_token, Event()
    monkeypatch.setenv("GPU_DEPLOYMENT_ID", "test")
    monkeypatch.setenv("GPU_BOOT_TOKEN", worker.token)
    monkeypatch.setenv("GPU_WORKER_KEY", "worker")
    work.pending.clear()
    with worker.operation() as allowed:
        assert allowed
        held = acquire(store.database, "published-job", "worker")
        assert held is not None
        release(store.database, held)
        # Queue lease is gone, but the surrounding synchronous publisher has not returned.
        assert controller.tick() == "busy"
        assert store.read().workers["worker"]["busy"]
    assert not store.read().workers["worker"]["busy"]
    assert not provider.deletes


def test_empty_worker_poll_does_not_reset_idle_timer(world):
    from threading import Event

    from src.services.orchestration.gpu.worker import ManagedWorker

    controller, store, provider, work = boot(world)
    worker = ManagedWorker.__new__(ManagedWorker)
    worker.store, worker.key, worker.token, worker.stop = store, "worker", store.read().boot_token, Event()
    work.pending.clear()
    controller.tick()
    expire_idle(store)
    with worker.operation() as allowed:
        assert allowed
        assert not store.read().workers["worker"]["busy"]
        assert controller.tick() == "draining"
    assert not provider.deletes


def test_stale_controller_response_cannot_override_new_leader(world):
    controller, store, provider, work = world
    second = Controller(store, controller.policy, controller.catalog, provider, lambda: work)
    original = provider.create

    def delayed(body):
        pod = original(body)
        with store.locked() as (_, c, now):
            c.leader_until = now - 1
        assert second.tick() == "starting"  # adopts the committed intent while first HTTP response is lost
        return pod

    provider.create = delayed
    assert controller.tick() == "created"
    assert store.read().owner == second.owner
    assert provider.creates == 1


def test_cpu_lane_preflight_rejects_insufficient_api_headroom(monkeypatch):
    from src.services.orchestration.gpu import cpu_worker

    monkeypatch.setattr(cpu_worker, "_live_ram_gb", lambda: 0.25)
    with pytest.raises(RuntimeError, match="headroom"):
        cpu_worker.preflight(GpuSettings())


def test_supervisor_returns_failure_if_api_child_exits(monkeypatch):
    import sys

    from src.services.orchestration.gpu.supervisor import supervise

    monkeypatch.setenv("GPU_CONTROLLER_RUN", "false")
    monkeypatch.setenv("GPU_CPU_LANE_ENABLED", "false")
    assert supervise([sys.executable, "-c", "raise SystemExit(0)"]) == 1


def test_cpu_lane_cannot_be_enabled_without_qualification_reference():
    with pytest.raises(ValueError, match="qualification"):
        GpuSettings(cpu_lane_enabled=True)


def test_managed_worker_initialization_checks_r2_and_cleans_probe(world, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.config import Settings
    from src.services.orchestration.artifacts.remote import ArtifactRemote
    from src.services.orchestration.gpu import worker as worker_module
    from tests.test_orchestration.memory_object_store import MemoryObjectStore

    controller, store, _, _ = boot(world)
    profile = controller.catalog.profiles[0]
    monkeypatch.setenv("GPU_BOOT_TOKEN", store.read().boot_token)
    monkeypatch.setenv("GPU_DEPLOYMENT_ID", "test")
    monkeypatch.setenv("GPU_INTENT_ID", store.read().intent)
    monkeypatch.setenv("GPU_EXPECTED_PROFILE", profile.model_dump_json())
    monkeypatch.setattr(worker_module, "bound_gpu", lambda: SimpleNamespace(total_gb=24))
    monkeypatch.setattr(worker_module, "_live_ram_gb", lambda: 64)
    monkeypatch.setattr(worker_module.shutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 1024**3))
    remote = ArtifactRemote(MemoryObjectStore())
    monkeypatch.setattr("src.services.orchestration.storage.artifact_remote", lambda _: remote)
    settings = Settings(
        _env_file=None,
        app_env="test",
        openai_api_key="fixture",
        database_url=store.database._url,
        product_worker_root=tmp_path / "workers",
    )
    managed = worker_module.ManagedWorker(settings, profile.execution)
    try:
        assert store.read().workers[managed.key]["ready"]
        assert remote.store.objects == {}
        assert remote.store.puts == 1
    finally:
        managed.close()
    assert managed.key not in store.read().workers


def test_reconcile_retains_pinned_ownership_when_catalog_rolls_forward(world):
    controller, store, provider, work = boot(world)
    previous = controller.catalog.profiles[0]
    changed = previous.model_copy(update={"image": "registry/new@sha256:" + "9" * 64})
    controller.catalog = controller.catalog.model_copy(update={"profiles": (changed,)})
    assert controller.tick() == "idle"  # New release demand must not keep the incompatible old image alive.
    expire_idle(store)
    assert controller.tick() == "draining"
    assert controller.tick() == "drained"
    assert controller.tick() == "terminating"
    assert provider.deletes == ["pod-1"]


def test_bad_worker_configuration_does_not_leave_ambiguous_create_intent(world):
    controller, store, provider, _ = world
    controller.policy.worker_env_file.write_text("ARTIFACT_S3_BUCKET=fixture\n")
    assert controller.tick() == "blocked"
    assert store.read().state == "absent"
    assert not store.read().intent
    assert provider.creates == 0


def test_api_readiness_remains_healthy_with_catalog_and_zero_workers(world, tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from src import main
    from src.config import Settings

    controller, store, _, _ = world
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(seal({"profiles": [controller.catalog.profiles[0].model_dump(mode="json")]})))
    settings = Settings(
        _env_file=None,
        app_env="test",
        openai_api_key="fixture",
        product_demo_required=False,
        product_demo_dir=tmp_path / "empty-library",
        product_gpu_release_catalog=path,
    )
    registry = SimpleNamespace(
        persistence=SimpleNamespace(database=store.database),
        job_profile=lambda: controller.catalog.profiles[0].execution,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr("src.services.orchestration.projects.get_project_registry", lambda: registry)
    response = asyncio.run(main.ready())
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["catalog_available"] and not payload["compute_available"]


def test_controller_process_retries_transient_database_outage(world, monkeypatch):
    from types import SimpleNamespace

    from psycopg import OperationalError

    from scripts.cloud import runpod_controller as cli

    controller, store, provider, _ = world
    ticks, waits = [], []

    class BrokenThenUnexpected:
        def __init__(self, *args, **kwargs):
            pass

        def tick(self):
            ticks.append(1)
            if len(ticks) == 1:
                raise OperationalError("fixture outage")
            raise RuntimeError("fixture unexpected bug")

    monkeypatch.setattr(cli, "GpuSettings", lambda: controller.policy)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url=store.database._url))
    monkeypatch.setattr(cli, "StateStore", lambda *_: store)
    monkeypatch.setattr(cli, "load_catalog", lambda _: controller.catalog)
    monkeypatch.setattr(cli, "Controller", BrokenThenUnexpected)
    monkeypatch.setattr(cli, "transport", lambda _: None)
    monkeypatch.setattr(cli, "RunPod", lambda _: provider)
    monkeypatch.setattr(cli, "Event", lambda: SimpleNamespace(wait=lambda seconds: waits.append(seconds)))
    assert cli.main(["run"]) == 1
    assert len(ticks) == 2 and waits == [controller.policy.poll_seconds]


def test_historic_owned_pod_is_cleaned_even_when_queue_empty_and_provisioning_disabled(world):
    controller, store, provider, work = boot(world)
    old_pod = dict(provider.pods[0])
    work.pending.clear()
    controller.tick()
    expire_idle(store)
    controller.tick()
    controller.tick()
    controller.tick()
    assert controller.tick() == "terminated_confirmed"
    provider.pods.append(old_pod)  # Simulates a false provider absence or stopped owned resource reappearing.
    controller.policy = controller.policy.model_copy(update={"autoprov_enabled": False})
    assert controller.tick() == "adopted_historic"
    assert controller.tick() == "drained"
    assert controller.tick() == "terminating"
    assert not provider.pods


def test_persisted_resource_wait_excludes_undersized_profile(tmp_path, profile, monkeypatch):
    from types import SimpleNamespace

    from src.services.orchestration.gpu import workload

    db = RuntimeDatabase(f"sqlite:///{tmp_path / 'queues.db'}")
    monkeypatch.setattr(workload, "waiting_jobs", lambda _: [])
    with db.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_scene_requests VALUES (?,?,?)",
            (
                "large",
                "queued",
                json.dumps(
                    {
                        "status": "queued",
                        "mode": "geometry",
                        "resource_wait": {"required_gb": {"vram": 40, "ram": 32, "disk": 50}},
                    }
                ),
            ),
        )
    large = profile.model_copy(update={"name": "larger", "min_vram_gb": 48})
    result = workload.scan_scope(db, SimpleNamespace(), ReleaseCatalog(profiles=(profile, large), checksum="fixture"))
    assert result.pending[0].profiles == ("larger",)
    result = workload.scan_scope(db, SimpleNamespace(), ReleaseCatalog(profiles=(profile,), checksum="fixture"))
    assert not result.pending and result.blocked


def test_max_pods_from_environment_is_accepted_as_documented(monkeypatch):
    """The runbook sets GPU_MAX_PODS=1; env values arrive as strings and must not crash the API at boot."""
    monkeypatch.setenv("GPU_MAX_PODS", "1")
    assert GpuSettings().max_pods == 1
    monkeypatch.setenv("GPU_MAX_PODS", "2")
    with pytest.raises(ValueError):
        GpuSettings()


class RefusingRunPod(FakeRunPod):
    """Provider that definitely refuses a create without allocating anything."""

    def __init__(self, error):
        super().__init__()
        self.refusal = error

    def create(self, body):
        self.creates += 1
        self.last_body = body
        raise self.refusal


def test_definite_create_refusal_retires_intent_and_retries_later(world):
    controller, store, _, work = world
    refusing = RefusingRunPod(ProviderError("inventory_unavailable", ambiguous=False, retry_after=60))
    controller.provider = refusing
    assert controller.tick() == "create_refused"
    c = store.read()
    assert (c.state, c.intent, c.pod, c.boot_token) == ("absent", "", "", "")
    assert c.error == "inventory_unavailable" and c.attempts == 1 and not c.drain
    with store.database.transaction() as tx:
        history = [json.loads(row[0]) for row in tx.execute("SELECT payload FROM r2s_gpu_history").fetchall()]
    assert history and history[-1]["state"] == "terminated"
    assert controller.tick() == "backoff"  # waits retry_after instead of hammering the provider
    with store.locked() as (_, current, now):
        current.retry_at = now - 1
    assert controller.tick() == "create_refused" and refusing.creates == 2


def test_repeated_definite_refusals_trip_the_circuit_breaker(world):
    controller, store, _, _ = world
    controller.provider = RefusingRunPod(ProviderError("provider_http", ambiguous=False, retry_after=1))
    for _ in range(controller.policy.max_provision_attempts):
        with store.locked() as (_, current, now):
            current.retry_at = now - 1
        assert controller.tick() == "create_refused"
    assert store.read().drain


def test_create_payload_matches_runpod_types(world, profile):
    controller, *_ = world
    payload = controller._payload(store_control(), profile.model_copy(update={"min_ram_gb": 31.5}), "qualified-gpu")
    assert payload["minRAMPerGPU"] == 32 and isinstance(payload["minRAMPerGPU"], int)
    assert payload["allowedCudaVersions"] == ["12.6"]
    newest = profile.model_copy(update={"cuda_versions": ("12.6", "12.8", "13.0")})
    assert "allowedCudaVersions" not in controller._payload(store_control(), newest, "qualified-gpu")


def store_control():
    from src.services.orchestration.gpu.state import Control

    return Control(deployment="test", intent="i", boot_token="t")


def test_transport_marks_only_definite_create_refusals_unambiguous(monkeypatch):
    import io
    import urllib.request
    from urllib.error import HTTPError

    from src.services.orchestration.gpu.provider import transport

    def respond(code, body):
        def fail(*args, **kwargs):
            raise HTTPError("https://fixture", code, "x", {}, io.BytesIO(body))

        monkeypatch.setattr(urllib.request, "urlopen", fail)

    call = transport("fixture")
    cases = [
        (400, b"cannot unmarshal number 32.0", False, "provider_http"),
        (500, b'{"error":"create pod: There are no instances currently available"}', False, "inventory_unavailable"),
        (500, b"internal error", True, "provider_http"),
        (401, b"denied", True, "auth"),
    ]
    for code, body, ambiguous, category in cases:
        respond(code, body)
        with pytest.raises(ProviderError) as error:
            call("POST", "/pods", {})
        assert (error.value.ambiguous, str(error.value)) == (ambiguous, category)
        assert b"instances" not in str(error.value).encode()
    respond(500, b"There are no instances currently available")
    with pytest.raises(ProviderError) as error:
        call("GET", "/pods", None)
    assert not error.value.ambiguous and str(error.value) == "provider_http"


def test_forget_unknown_only_when_no_pod_carries_the_intent_name(world):
    controller, store, provider, _ = world
    provider.create_error = ProviderError("timeout", ambiguous=True)
    assert controller.tick() == "provider_error"
    intent = store.read().intent
    # FakeRunPod allocated the Pod before failing: the name proves it exists, so nothing is forgotten.
    assert controller.forget_unknown() == "pod_exists"
    provider.pods.clear()
    assert controller.forget_unknown() == "forgotten"
    c = store.read()
    assert (c.state, c.intent) == ("absent", "") and c.error == "operator_forgot_unallocated_intent"
    with store.database.transaction() as tx:
        retired = [json.loads(r[0]) for r in tx.execute("SELECT payload FROM r2s_gpu_history").fetchall()]
    assert any(h["intent"] == intent and h["state"] == "terminated" for h in retired)
    assert controller.forget_unknown() == "nothing_to_forget"


def test_rest_pod_shape_with_top_level_gpu_count_is_a_valid_allocation(world):
    """RunPod REST v1 returns gpuCount at the top level, "gpu": null and "image": null next to imageName."""
    controller, store, provider, _ = world
    assert controller.tick() == "created"
    pod = provider.pods[0]
    pod.pop("gpu")
    pod.update({"gpu": None, "gpuCount": 1, "image": None, "machine": {"gpuTypeId": "qualified-gpu"}})
    with store.locked() as (_, c, now):
        c.workers["worker"] = {"ready": True, "busy": False, "heartbeat": now}
    assert controller.tick() == "ready"
