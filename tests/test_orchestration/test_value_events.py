"""Nhật ký sự kiện giá trị: ghi/đọc append-only và ghi lỗi không làm hỏng thao tác chính."""

import ast
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.value import list_events, record_event
from src.services.orchestration.value.events import HUMAN_OPERATIONS, SYSTEM_OPERATIONS, operation_origin


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


_SRC = Path(__file__).resolve().parents[2] / "src"
#: Tên biến được phép làm operation không literal: `action` (ObjectAction) và `operation` (chuyển tiếp trong editor).
_FORWARDED_OPERATION_NAMES = {"action", "operation"}


def _operations_passed_to_editor() -> tuple[set[str], set[str]]:
    """Mọi chuỗi literal truyền làm operation cho publish_next/_publish_reserved; và các tên biến không literal."""
    literals: set[str] = set()
    names: set[str] = set()
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"publish_next", "_publish_reserved"} or len(node.args) < 4:
                continue
            operation = node.args[3]
            if isinstance(operation, ast.Constant) and isinstance(operation.value, str):
                literals.add(operation.value)
            elif isinstance(operation, ast.Name):
                names.add(operation.id)
            else:
                pytest.fail(f"{path}:{node.lineno}: operation không phải literal hoặc tên biến đã biết")
    return literals, names


def test_every_editor_operation_in_src_is_classified_exactly_once() -> None:
    from typing import get_args

    from src.services.orchestration.scene.objects import ObjectAction

    literals, names = _operations_passed_to_editor()
    assert names <= _FORWARDED_OPERATION_NAMES, f"tên biến lạ làm operation: {names - _FORWARDED_OPERATION_NAMES}"
    object_actions = set(get_args(ObjectAction))
    operations = literals | object_actions  # ObjectAction đi qua biến `action`, nên lấy từ Literal
    assert {"objectify", "transform_edit", "publish_initial", "restore_revision"} <= operations

    assert HUMAN_OPERATIONS.isdisjoint(SYSTEM_OPERATIONS)
    unclassified = operations - HUMAN_OPERATIONS - SYSTEM_OPERATIONS
    assert unclassified == set(), f"thao tác chưa phân loại người/hệ thống: {sorted(unclassified)}"
    assert all(operation_origin(operation) != "unknown" for operation in operations)


def test_unknown_operation_is_reported_as_unknown_not_guessed() -> None:
    assert operation_origin("brand_new_operation") == "unknown"
    assert operation_origin("move") == "unknown"
    assert operation_origin("objectify") == "system"
    assert operation_origin("confirm") == "human"
