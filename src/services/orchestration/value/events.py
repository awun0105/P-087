"""Nhật ký sự kiện giá trị (architecture §15.2): bảng `r2s_value_events`, chỉ ghi thêm.

Ghi lỗi nhật ký không bao giờ làm hỏng thao tác chính: `record_event` log cảnh báo rồi bỏ qua.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from src.models.contracts.artifacts import JsonObject
from src.services.orchestration.jobs.database import RuntimeDatabase

EventKind = Literal["scene_edit", "operator_time", "walk_session"]

logger = logging.getLogger(__name__)


class ValueEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    job_id: str
    at: datetime
    kind: EventKind
    actor_id: str | None
    payload: JsonObject


def record_event(
    database: RuntimeDatabase,
    job_id: str,
    kind: EventKind,
    payload: JsonObject,
    *,
    actor_id: str | None = None,
    at: datetime | None = None,
) -> None:
    """Thêm một sự kiện; lỗi DB hoặc dữ liệu sai chỉ log warning, không raise."""
    try:
        event = ValueEvent(
            event_id=uuid4().hex,
            job_id=job_id,
            at=(at or datetime.now(UTC)).astimezone(UTC),
            kind=kind,
            actor_id=actor_id,
            payload=payload,
        )
        with database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_value_events(event_id,job_id,at,kind,actor_id,payload) VALUES (?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.job_id,
                    event.at.isoformat(timespec="microseconds"),
                    event.kind,
                    event.actor_id,
                    json.dumps(event.payload, sort_keys=True),
                ),
            )
    except Exception:  # noqa: BLE001 - nhật ký là phụ; mọi lỗi phải bị nuốt tại đây, không được chặn thao tác chính
        logger.warning("Không ghi được sự kiện giá trị %s của job %s", kind, job_id, exc_info=True)


def list_events(
    database: RuntimeDatabase,
    job_id: str,
    kinds: set[EventKind] | None = None,
) -> list[ValueEvent]:
    """Sự kiện của một job theo thời điểm `at` tăng dần; `kinds` rỗng/None nghĩa là mọi loại."""
    query = "SELECT event_id,job_id,at,kind,actor_id,payload FROM r2s_value_events WHERE job_id=?"
    parameters: list[str] = [job_id]
    if kinds:
        ordered = sorted(kinds)
        query += " AND kind IN (" + ",".join("?" for _ in ordered) + ")"
        parameters.extend(ordered)
    query += " ORDER BY at, event_id"
    with database.transaction() as tx:
        rows = tx.execute(query, tuple(parameters)).fetchall()
    return [
        ValueEvent(
            event_id=row[0],
            job_id=row[1],
            at=datetime.fromisoformat(row[2]),
            kind=row[3],
            actor_id=row[4],
            payload=json.loads(row[5]),
        )
        for row in rows
    ]
