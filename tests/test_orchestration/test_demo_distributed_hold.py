"""Readers of a PostgreSQL demo session must not keep a pooled connection open while the request runs."""

from contextlib import contextmanager

import pytest

from src.services.orchestration.samples import distributed
from src.services.orchestration.samples.sessions import DemoSessionUnavailableError

SESSION = "a" * 32


class _Database:
    open_transactions = 0

    def __init__(self, url: str, lock_granted: bool = True) -> None:
        self.lock_granted = lock_granted

    @contextmanager
    def transaction(self, write: bool = False):
        _Database.open_transactions += 1
        try:
            yield self
        finally:
            _Database.open_transactions -= 1

    def execute(self, statement: str, parameters: tuple = ()):
        granted = self.lock_granted

        class _Cursor:
            def fetchone(self):
                return (granted,)

        return _Cursor()


@pytest.fixture
def fake_db(monkeypatch):
    _Database.open_transactions = 0
    monkeypatch.setattr(distributed, "RuntimeDatabase", _Database)
    monkeypatch.setattr(distributed, "_validate", lambda session_id: session_id)
    monkeypatch.setattr(distributed, "get", lambda settings, session_id: None)
    return monkeypatch


class _Settings:
    database_url = "postgresql://example/db"


def test_reader_releases_connection_before_request_runs(fake_db):
    with distributed.hold(_Settings(), SESSION) as held:
        assert held is True
        assert _Database.open_transactions == 0


def test_reader_is_refused_while_cleanup_holds_the_session(fake_db):
    fake_db.setattr(distributed, "RuntimeDatabase", lambda url: _Database(url, lock_granted=False))
    with pytest.raises(DemoSessionUnavailableError), distributed.hold(_Settings(), SESSION):
        pass
    assert _Database.open_transactions == 0


def test_worker_keeps_its_lock_for_the_whole_run(fake_db):
    with distributed.hold(_Settings(), SESSION, worker=True) as held:
        assert held is True
        assert _Database.open_transactions == 1
