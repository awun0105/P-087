"""T-046: one failing queue step must not end the worker loop."""

import logging
import sqlite3

import pytest

from src.services.orchestration.jobs.worker_cli import QueueGuard, poll_queues


def _boom() -> bool:
    raise RuntimeError("boom")


def test_guard_returns_step_result_and_resets_failures() -> None:
    guard = QueueGuard()
    guard.run("scene", _boom)
    guard.run("scene", _boom)
    assert guard.run("scene", lambda: True) is True
    assert guard.backoff_seconds() == 0


def test_guard_swallows_exception_and_backs_off() -> None:
    guard = QueueGuard()
    delays = []
    for _ in range(3):
        assert guard.run("scene", _boom) is False
        delays.append(guard.backoff_seconds())
    assert delays == [1, 2, 4]
    for _ in range(7):
        guard.run("scene", _boom)
    assert guard.backoff_seconds() == 60


def test_guard_lets_keyboard_interrupt_through() -> None:
    def interrupted() -> bool:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        QueueGuard().run("scene", interrupted)


def test_guard_logs_queue_name(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        QueueGuard().run("scene", _boom)
    assert "scene" in caplog.text
    assert "lần 1" in caplog.text


def test_worker_loop_survives_scene_queue_error() -> None:
    """A locked database in the scene queue must not stop later queues in the same round."""
    calls: list[str] = []

    def scene() -> bool:
        calls.append("scene")
        raise sqlite3.OperationalError("database is locked")

    def validation() -> bool:
        calls.append("validation")
        return True

    guard = QueueGuard()
    handled = poll_queues(guard, [("pipeline", lambda: False), ("scene", scene), ("validation", validation)])
    assert handled is True
    assert calls == ["scene", "validation"]
    assert guard.backoff_seconds() == 1


def test_poll_queues_stops_at_first_handled_queue() -> None:
    calls: list[str] = []
    steps = [("pipeline", lambda: calls.append("pipeline") or True), ("scene", lambda: calls.append("scene") or True)]
    assert poll_queues(QueueGuard(), steps) is True
    assert calls == ["pipeline"]
