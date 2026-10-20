"""PostgreSQL connection reuse in RuntimeDatabase; requires an explicitly disposable local DB."""

import os
from urllib.parse import urlsplit

import pytest

from src.services.orchestration.jobs import database as runtime_database
from src.services.orchestration.jobs.database import RuntimeDatabase


@pytest.fixture
def database():
    url = os.environ.get("R2S_GPU_TEST_DATABASE_URL")
    if not url:
        pytest.skip("R2S_GPU_TEST_DATABASE_URL is not configured")
    parsed = urlsplit(url)
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.path == "/r2s_gpu_test"
    runtime_database._IDLE.clear()
    yield RuntimeDatabase(url)
    runtime_database._IDLE.clear()


def _backend_pid(database: RuntimeDatabase) -> int:
    with database.transaction() as tx:
        return tx.execute("SELECT pg_backend_pid()").fetchone()[0]


def test_sequential_transactions_reuse_one_connection(database):
    assert _backend_pid(database) == _backend_pid(database)


def test_failed_transaction_rolls_back_and_connection_stays_usable(database):
    with database.transaction(write=True) as tx:
        tx.execute("CREATE TABLE IF NOT EXISTS r2s_reuse_probe (id INTEGER PRIMARY KEY)")
        tx.execute("DELETE FROM r2s_reuse_probe")
    with pytest.raises(RuntimeError):
        with database.transaction(write=True) as tx:
            tx.execute("INSERT INTO r2s_reuse_probe(id) VALUES (1)")
            raise RuntimeError("abort")
    with database.transaction() as tx:
        assert tx.execute("SELECT count(*) FROM r2s_reuse_probe").fetchone()[0] == 0


def test_set_local_does_not_leak_into_the_next_transaction(database):
    with database.transaction() as tx:
        tx.execute("SET LOCAL search_path TO pg_catalog")
    with database.transaction() as tx:
        assert tx.execute("SHOW search_path").fetchone()[0] != "pg_catalog"


def test_connection_closed_by_server_is_replaced(database):
    first = _backend_pid(database)
    # Kill the pooled backend from a separate connection, then the next transaction must still work.
    import psycopg

    with psycopg.connect(os.environ["R2S_GPU_TEST_DATABASE_URL"], autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (first,))
    assert _backend_pid(database) != first


def test_stale_idle_connection_is_not_reused(database, monkeypatch):
    first = _backend_pid(database)
    monkeypatch.setattr(runtime_database, "_IDLE_SECONDS", -1.0)
    assert _backend_pid(database) != first
