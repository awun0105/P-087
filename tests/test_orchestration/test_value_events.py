"""Nhật ký sự kiện giá trị: ghi/đọc append-only và ghi lỗi không làm hỏng thao tác chính."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.value import list_events, record_event


@pytest.fixture
def database(tmp_path: Path) -> RuntimeDatabase:
    return RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")


def test_recorded_events_are_listed_by_time_and_filtered_by_kind(database: RuntimeDatabase) -> None:
    base = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    record_event(database, "job-a", "walk_session", {"outcome": "completed"}, at=base + timedelta(seconds=5))
    record_event(database, "job-a", "scene_edit", {"operation": "move"}, at=base)
    record_event(database, "job-b", "scene_edit", {"operation": "move"}, at=base)

    events = list_events(database, "job-a")

    assert [event.kind for event in events] == ["scene_edit", "walk_session"]
    assert events[0].payload == {"operation": "move"}
    assert events[0].at == base
    assert [event.kind for event in list_events(database, "job-a", {"walk_session"})] == ["walk_session"]
    assert list_events(database, "job-missing") == []


def test_record_keeps_actor_and_uses_utc_timestamp(database: RuntimeDatabase) -> None:
    local = datetime(2026, 10, 16, 16, 0, tzinfo=UTC).astimezone(datetime.now().astimezone().tzinfo)

    record_event(database, "job-a", "operator_time", {"active_seconds": 42}, actor_id="user-1", at=local)

    (event,) = list_events(database, "job-a")
    assert event.actor_id == "user-1"
    assert event.at.utcoffset() == timedelta(0)


def test_database_failure_is_logged_and_never_raised(
    database: RuntimeDatabase, caplog: pytest.LogCaptureFixture
) -> None:
    class BrokenDatabase:
        def transaction(self, *, write: bool = False):  # noqa: ANN201 - test double
            raise RuntimeError("disk full")

    with caplog.at_level(logging.WARNING, logger="src.services.orchestration.value.events"):
        record_event(BrokenDatabase(), "job-a", "scene_edit", {"operation": "move"})  # type: ignore[arg-type]

    assert "Không ghi được sự kiện giá trị scene_edit của job job-a" in caplog.text
    assert list_events(database, "job-a") == []


def test_invalid_payload_is_dropped_with_a_warning(database: RuntimeDatabase, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="src.services.orchestration.value.events"):
        record_event(database, "job-a", "scene_edit", {"bad": object()})  # type: ignore[dict-item]

    assert "Không ghi được sự kiện" in caplog.text
    assert list_events(database, "job-a") == []
