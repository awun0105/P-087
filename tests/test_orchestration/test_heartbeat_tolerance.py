"""T-049: a brief database outage must not abort long worker runs."""

import sqlite3
from datetime import timedelta

from src.services.orchestration.jobs.database import RuntimeStateConflictError, is_transient_database_error
from src.services.orchestration.jobs.heartbeat import HeartbeatTolerance


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _locked() -> sqlite3.OperationalError:
    return sqlite3.OperationalError("database is locked")


def test_transient_error_within_window_is_tolerated() -> None:
    clock = _Clock()
    tolerance = HeartbeatTolerance(timedelta(seconds=90), clock=clock)
    clock.now = 20
    assert tolerance.tolerate(_locked()) is True
    clock.now = 40
    assert tolerance.tolerate(_locked()) is True


def test_transient_error_after_two_thirds_ttl_gives_up() -> None:
    clock = _Clock()
    tolerance = HeartbeatTolerance(timedelta(seconds=90), clock=clock)
    clock.now = 61
    assert tolerance.tolerate(_locked()) is False


def test_success_resets_window() -> None:
    clock = _Clock()
    tolerance = HeartbeatTolerance(timedelta(seconds=90), clock=clock)
    clock.now = 50
    assert tolerance.tolerate(_locked()) is True
    clock.now = 55
    tolerance.succeeded()
    clock.now = 100
    assert tolerance.tolerate(_locked()) is True


def test_non_transient_error_gives_up_immediately() -> None:
    assert HeartbeatTolerance(timedelta(seconds=90), clock=_Clock()).tolerate(ValueError("x")) is False


def test_is_transient_database_error_cases() -> None:
    assert is_transient_database_error(_locked())
    assert is_transient_database_error(sqlite3.OperationalError("database is BUSY"))
    assert not is_transient_database_error(sqlite3.OperationalError("no such table: r2s_jobs"))
    assert is_transient_database_error(ConnectionResetError())
    assert is_transient_database_error(TimeoutError())
    assert not is_transient_database_error(RuntimeStateConflictError("x"))
    assert not is_transient_database_error(ValueError("x"))


def test_psycopg_operational_error_is_transient() -> None:
    import psycopg

    assert is_transient_database_error(psycopg.OperationalError("server closed the connection unexpectedly"))
    assert is_transient_database_error(psycopg.InterfaceError("connection already closed"))
