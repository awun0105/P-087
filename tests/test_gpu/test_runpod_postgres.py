"""Real PostgreSQL lock/scope acceptance; requires an explicitly disposable local DB."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from src.services.orchestration.gpu.catalog import ReleaseCatalog
from src.services.orchestration.gpu.controller import Controller
from src.services.orchestration.gpu.state import StateStore, claim_allowed
from src.services.orchestration.gpu.workload import scan_scope
from src.services.orchestration.jobs.database import RuntimeDatabase, demo_database_url

pytest_plugins = ["tests.test_gpu.test_runpod_lifecycle"]


@pytest.fixture
def database():
    url = os.environ.get("R2S_GPU_TEST_DATABASE_URL")
    if not url:
        pytest.skip("R2S_GPU_TEST_DATABASE_URL is not configured")
    parsed = urlsplit(url)
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.path == "/r2s_gpu_test"
    return RuntimeDatabase(url)


def test_two_controller_replicas_create_exactly_once(database, world):
    controller, _, provider, work = world
    store = StateStore(database, uuid4().hex)
    first = Controller(store, controller.policy, controller.catalog, provider, lambda: work)
    second = Controller(store, controller.policy, controller.catalog, provider, lambda: work)
    barrier = Barrier(2)

    def tick(c):
        barrier.wait(timeout=5)
        return c.tick()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(tick, [first, second]))
    assert sorted(outcomes) == ["created", "follower"]
    assert provider.creates == 1
    assert store.read().pod == "pod-1"


def test_claim_shared_lock_serializes_drain_and_scoped_claims(database, monkeypatch):
    deployment = uuid4().hex
    store = StateStore(database, deployment)
    with store.locked() as (_, c, _):
        c.state, c.boot_token = "ready", "fixture-token"
    monkeypatch.setenv("GPU_DEPLOYMENT_ID", deployment)
    monkeypatch.setenv("GPU_BOOT_TOKEN", "fixture-token")
    session_id = uuid4().hex
    with database.transaction(write=True) as tx:
        tx.execute(f'CREATE SCHEMA "r2s_demo_{session_id}"')
    scoped = RuntimeDatabase(demo_database_url(database._url, session_id))
    entered, release, drained = Event(), Event(), Event()

    def claim():
        with scoped.transaction(write=True) as tx:
            assert claim_allowed(tx)
            entered.set()
            assert release.wait(5)
            tx.execute(
                "INSERT INTO r2s_job_leases VALUES (?,?,?,?)",
                ("shared-id", "lease", "worker", "2099-01-01T00:00:00+00:00"),
            )

    def drain():
        assert entered.wait(5)
        with store.locked() as (_, c, _):
            c.state = "draining"
        drained.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            claiming, draining = pool.submit(claim), pool.submit(drain)
            assert entered.wait(5)
            assert not drained.wait(0.1), "drain must wait for in-flight claim transaction"
            release.set()
            claiming.result(timeout=5)
            draining.result(timeout=5)
        with scoped.transaction(write=True) as tx:
            assert not claim_allowed(tx)
        with database.transaction() as tx:
            assert not tx.execute("SELECT 1 FROM r2s_job_leases WHERE job_id=?", ("shared-id",)).fetchone()
        with scoped.transaction() as tx:
            assert tx.execute("SELECT 1 FROM r2s_job_leases WHERE job_id=?", ("shared-id",)).fetchone()
    finally:
        release.set()
        with database.transaction(write=True) as tx:
            tx.execute(f'DROP SCHEMA "r2s_demo_{session_id}" CASCADE')


def test_demo_gpu_work_counts_when_main_queue_empty(database, profile, monkeypatch):
    from types import SimpleNamespace

    from src.services.orchestration.gpu import workload

    monkeypatch.setattr(workload, "waiting_jobs", lambda _: [])
    session_id = uuid4().hex
    with database.transaction(write=True) as tx:
        tx.execute(f'CREATE SCHEMA "r2s_demo_{session_id}"')
    scoped = RuntimeDatabase(demo_database_url(database._url, session_id))
    try:
        with scoped.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_scene_requests VALUES (?,?,?)",
                ("same-id", "queued", json.dumps({"status": "queued", "mode": "geometry"})),
            )
        result = scan_scope(scoped, SimpleNamespace(), ReleaseCatalog(profiles=(profile,), checksum="fixture"))
        assert result.complete and len(result.pending) == 1
        assert result.pending[0].scope == f"r2s_demo_{session_id}"
        with database.transaction() as tx:
            assert tx.execute("SELECT COUNT(*) FROM r2s_scene_requests").fetchone()[0] == 0
    finally:
        with database.transaction(write=True) as tx:
            tx.execute(f'DROP SCHEMA "r2s_demo_{session_id}" CASCADE')
