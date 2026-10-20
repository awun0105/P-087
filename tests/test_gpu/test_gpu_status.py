"""Read-only GPU capacity shown to people waiting for a job."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.services.orchestration.gpu.status import DEFAULT_STARTUP_SECONDS, expected_startup_seconds, gpu_capacity
from src.services.orchestration.jobs.database import RuntimeDatabase

DEPLOYMENT = "real2sim-test"


@pytest.fixture
def database(tmp_path: Path) -> RuntimeDatabase:
    return RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")


def _control(database: RuntimeDatabase, **payload) -> None:
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_gpu_control(deployment_id,payload) VALUES (?,?) "
            "ON CONFLICT(deployment_id) DO UPDATE SET payload=excluded.payload",
            (DEPLOYMENT, json.dumps({"deployment": DEPLOYMENT, **payload})),
        )


def _history(database: RuntimeDatabase, intent: str, **payload) -> None:
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_gpu_history(intent_id,deployment_id,payload) VALUES (?,?,?)",
            (intent, DEPLOYMENT, json.dumps({"deployment": DEPLOYMENT, "intent": intent, **payload})),
        )


def test_unmanaged_without_deployment(database: RuntimeDatabase) -> None:
    assert gpu_capacity(database, "").state == "unmanaged"
    assert gpu_capacity(None, DEPLOYMENT).state == "unmanaged"


def test_off_before_any_pod_uses_default_estimate(database: RuntimeDatabase) -> None:
    capacity = gpu_capacity(database, DEPLOYMENT)
    assert capacity.state == "off"
    assert capacity.expected_startup_seconds == DEFAULT_STARTUP_SECONDS
    assert capacity.sample_count == 0


def test_starting_reports_since_and_counts_down(database: RuntimeDatabase) -> None:
    started = datetime.now(UTC).timestamp() - 120
    _control(database, state="starting", created_at=started, phase_since=started + 30)
    capacity = gpu_capacity(database, DEPLOYMENT)
    assert capacity.state == "starting"
    assert capacity.since is not None and abs(capacity.since.timestamp() - started) < 1
    assert 119 <= (capacity.elapsed_seconds or 0) <= 125
    assert capacity.remaining_seconds == pytest.approx(DEFAULT_STARTUP_SECONDS - capacity.elapsed_seconds, abs=1)


def test_remaining_never_negative_after_estimate(database: RuntimeDatabase) -> None:
    started = datetime.now(UTC).timestamp() - 5000
    _control(database, state="provisioning", created_at=started, phase_since=started)
    assert gpu_capacity(database, DEPLOYMENT).remaining_seconds == 0


def test_estimate_is_median_of_cold_starts_that_reached_ready(database: RuntimeDatabase) -> None:
    _history(database, "a", state="terminated", phase_seconds={"provisioning": 20, "starting": 400, "ready": 900})
    _history(database, "b", state="terminated", phase_seconds={"provisioning": 40, "starting": 560, "ready": 60})
    _history(database, "c", state="terminated", phase_seconds={"provisioning": 10, "starting": 290, "busy": 30})
    # Never reached ready (failed preflight): excluded from the estimate.
    _history(database, "d", state="terminated", phase_seconds={"provisioning": 5, "starting": 1200})
    capacity = gpu_capacity(database, DEPLOYMENT)
    assert capacity.expected_startup_seconds == 420
    assert capacity.sample_count == 3


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("ready", "ready"),
        ("busy", "ready"),
        ("draining", "draining"),
        ("terminating", "draining"),
        ("unknown", "blocked"),
        ("absent", "off"),
        ("terminated", "off"),
    ],
)
def test_controller_states_map_to_user_states(database: RuntimeDatabase, state: str, expected: str) -> None:
    _control(database, state=state, phase_since=datetime.now(UTC).timestamp())
    assert gpu_capacity(database, DEPLOYMENT).state == expected


def test_drained_after_failed_attempts_is_blocked(database: RuntimeDatabase) -> None:
    _control(database, state="absent", error="no_compatible_inventory_within_price", drain=True)
    assert gpu_capacity(database, DEPLOYMENT).state == "blocked"


def test_reads_in_one_transaction(database: RuntimeDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    opened = []
    original = RuntimeDatabase.transaction

    def counting(self, *args, **kwargs):
        opened.append(kwargs.get("write", False))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(RuntimeDatabase, "transaction", counting)
    gpu_capacity(database, DEPLOYMENT)
    assert opened == [False]


def test_history_without_phases_is_ignored() -> None:
    assert expected_startup_seconds([{"state": "ready"}, {}]) == (DEFAULT_STARTUP_SECONDS, 0)


def test_route_reads_the_configured_deployment(database: RuntimeDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from src.api.studio import gpu

    monkeypatch.setattr(gpu.deps, "registry", lambda: SimpleNamespace(persistence=SimpleNamespace(database=database)))
    monkeypatch.delenv("GPU_DEPLOYMENT_ID", raising=False)
    assert gpu.get_gpu_status().state == "unmanaged"
    monkeypatch.setenv("GPU_DEPLOYMENT_ID", DEPLOYMENT)
    _control(database, state="starting", created_at=datetime.now(UTC).timestamp())
    assert gpu.get_gpu_status().state == "starting"


def test_route_is_served_behind_contributor_auth(database: RuntimeDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_contributor
    from src.api.studio import gpu, router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    monkeypatch.setattr(gpu.deps, "registry", lambda: SimpleNamespace(persistence=SimpleNamespace(database=database)))
    monkeypatch.setenv("GPU_DEPLOYMENT_ID", DEPLOYMENT)
    app.dependency_overrides[require_contributor] = lambda: SimpleNamespace(role="guest")
    response = TestClient(app).get("/api/v1/gpu/status")
    assert response.status_code == 200
    assert response.json()["state"] == "off"
    assert response.json()["expected_startup_seconds"] == DEFAULT_STARTUP_SECONDS
