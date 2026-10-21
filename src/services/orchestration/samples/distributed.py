"""PostgreSQL ownership and R2 cleanup for disposable workspaces on separate hosts."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from src.config import Settings
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeTransaction
from src.services.orchestration.storage import artifact_remote

if TYPE_CHECKING:
    from src.services.orchestration.samples.sessions import DemoSession

logger = logging.getLogger(__name__)


def enabled(settings: Settings) -> bool:
    return (
        settings.database_url.startswith(("postgres://", "postgresql://"))
        and "#" not in settings.database_url
        and not settings.product_demo_session_worker
    )


def _validate(session_id: str) -> str:
    if re.fullmatch(r"[a-f0-9]{32}", session_id) is None:
        from src.services.orchestration.samples.sessions import DemoSessionUnavailableError

        raise DemoSessionUnavailableError("Phiên demo không hợp lệ")
    return session_id


def unpublished(settings: Settings, sample_id: str) -> bool:
    if not enabled(settings):
        return False
    with RuntimeDatabase(settings.database_url).transaction() as tx:
        return tx.execute("SELECT 1 FROM r2s_demo_unpublished WHERE sample_id=?", (sample_id,)).fetchone() is not None


def reserve(settings: Settings, sample_id: str) -> str:
    """Reserve capacity and create the namespace atomically before copying any files."""
    from src.services.orchestration.samples.bundle import DemoUnavailableError

    if artifact_remote(settings) is None:
        raise DemoUnavailableError("Demo phân tán cần PostgreSQL và kho file S3/R2")
    session_id = uuid4().hex
    now = datetime.now(UTC)
    with RuntimeDatabase(settings.database_url).transaction(write=True) as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtextextended('real2sim.demo.capacity',0))")
        if tx.execute("SELECT 1 FROM r2s_demo_unpublished WHERE sample_id=?", (sample_id,)).fetchone():
            raise DemoUnavailableError("Mẫu đã được bỏ khỏi thư viện demo")
        count = tx.execute("SELECT COUNT(*) FROM r2s_demo_sessions WHERE state IN ('creating','open')").fetchone()
        if count is not None and count[0] >= settings.product_demo_max_sessions:
            raise DemoUnavailableError("Các phiên demo đang đầy; thử lại sau khi có người thoát")
        # UUID validated here; SQL identifiers cannot be supplied by the browser.
        tx.execute(f'CREATE SCHEMA "r2s_demo_{session_id}"')
        tx.execute(
            "INSERT INTO r2s_demo_sessions(session_id,state,created_at,last_seen_at,expires_at,payload) VALUES (?,?,?,?,?,?)",
            (
                session_id,
                "creating",
                now.isoformat(),
                now.isoformat(),
                (now + timedelta(seconds=settings.product_demo_session_seconds)).isoformat(),
                "{}",
            ),
        )
    return session_id


def publish(settings: Settings, session: DemoSession) -> None:
    with RuntimeDatabase(settings.database_url).transaction(write=True) as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", (f"r2s.demo.sample:{session.sample_id}",))
        if tx.execute("SELECT 1 FROM r2s_demo_unpublished WHERE sample_id=?", (session.sample_id,)).fetchone():
            raise ValueError("Sample was unpublished during session initialization")
        result = tx.execute(
            "UPDATE r2s_demo_sessions SET state='open',last_seen_at=?,expires_at=?,payload=? "
            "WHERE session_id=? AND state='creating'",
            (
                datetime.now(UTC).isoformat(),
                session.expires_at.isoformat(),
                session.model_dump_json(),
                session.session_id,
            ),
        )
        if result.rowcount != 1:
            raise ValueError("Demo session was closed during initialization")


def get(settings: Settings, session_id: str) -> DemoSession:
    from src.services.orchestration.samples.sessions import DemoSession, DemoSessionUnavailableError

    _validate(session_id)
    with RuntimeDatabase(settings.database_url).transaction() as tx:
        row = tx.execute(
            "SELECT state,last_seen_at,expires_at,payload FROM r2s_demo_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    now = datetime.now(UTC)
    if (
        row is None
        or row[0] != "open"
        or datetime.fromisoformat(row[2]) <= now
        or datetime.fromisoformat(row[1]) + timedelta(seconds=settings.product_demo_idle_seconds) <= now
    ):
        raise DemoSessionUnavailableError("Phiên demo đã kết thúc; mở lại mẫu để tạo phiên mới")
    session = DemoSession.model_validate_json(row[3])
    if session.session_id != session_id:
        raise DemoSessionUnavailableError("Phiên demo không hợp lệ")
    return session


def touch(settings: Settings, session_id: str) -> None:
    get(settings, session_id)
    with RuntimeDatabase(settings.database_url).transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_demo_sessions SET last_seen_at=? WHERE session_id=? AND state='open'",
            (datetime.now(UTC).isoformat(), session_id),
        )


def close(settings: Settings, session_id: str) -> None:
    _validate(session_id)
    with RuntimeDatabase(settings.database_url).transaction(write=True) as tx:
        tx.execute("UPDATE r2s_demo_sessions SET state='closed' WHERE session_id=?", (session_id,))


def republish(settings: Settings, sample_id: str) -> None:
    with RuntimeDatabase(settings.database_url).transaction(write=True) as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", (f"r2s.demo.sample:{sample_id}",))
        tx.execute("DELETE FROM r2s_demo_unpublished WHERE sample_id=?", (sample_id,))


def unpublish(settings: Settings, sample_id: str) -> None:
    with RuntimeDatabase(settings.database_url).transaction(write=True) as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", (f"r2s.demo.sample:{sample_id}",))
        tx.execute(
            "INSERT INTO r2s_demo_unpublished(sample_id,at) VALUES (?,?) ON CONFLICT(sample_id) DO NOTHING",
            (sample_id, datetime.now(UTC).isoformat()),
        )
        rows = tx.execute("SELECT session_id,payload FROM r2s_demo_sessions WHERE state='open'").fetchall()
        from src.services.orchestration.samples.sessions import DemoSession

        for session_id, payload in rows:
            if DemoSession.model_validate_json(payload).sample_id == sample_id:
                tx.execute("UPDATE r2s_demo_sessions SET state='closed' WHERE session_id=?", (session_id,))


@contextmanager
def hold(settings: Settings, session_id: str, *, worker: bool = False) -> Iterator[bool]:
    """A database lock fences active readers/workers against cleanup across hosts.

    Readers only check that cleanup is not running, then release the connection: holding one pooled connection per
    request (including streaming large scene files) while the handler checks out its own connection deadlocks the
    transaction pooler. Cleanup only removes closed sessions, which `get` already rejects.
    """
    _validate(session_id)
    if not worker:
        with RuntimeDatabase(settings.database_url).transaction() as tx:
            shared = tx.execute(
                "SELECT pg_try_advisory_xact_lock_shared(hashtextextended(?,0))", (f"r2s.demo.session:{session_id}",)
            ).fetchone()
        if shared is None or not shared[0]:
            from src.services.orchestration.samples.sessions import DemoSessionUnavailableError

            raise DemoSessionUnavailableError("Phiên demo đang được thu hồi")
        get(settings, session_id)
        yield True
        return
    with RuntimeDatabase(settings.database_url).transaction() as tx:
        tx.execute("SET LOCAL idle_in_transaction_session_timeout=0")
        row = tx.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(?,0))", (f"r2s.demo.worker:{session_id}",)
        ).fetchone()
        if row is None or not row[0]:
            yield False
            return
        shared = tx.execute(
            "SELECT pg_try_advisory_xact_lock_shared(hashtextextended(?,0))", (f"r2s.demo.session:{session_id}",)
        ).fetchone()
        if shared is None or not shared[0]:
            from src.services.orchestration.samples.sessions import DemoSessionUnavailableError

            raise DemoSessionUnavailableError("Phiên demo đang được thu hồi")
        get(settings, session_id)
        yield True


def list_sessions(settings: Settings) -> list[str]:
    with RuntimeDatabase(settings.database_url).transaction() as tx:
        return [
            row[0]
            for row in tx.execute(
                "SELECT session_id FROM r2s_demo_sessions WHERE state='open' ORDER BY created_at,session_id"
            ).fetchall()
        ]


def output_prefix(settings: Settings, session_id: str) -> str:
    _validate(session_id)
    return "/".join(part for part in (settings.artifact_s3_prefix.strip("/"), "demo-sessions", session_id) if part)


def _summary(tx: RuntimeTransaction, session_id: str, payload: str) -> str:
    """Retain timing observations, never scene edits, raw input URIs or capabilities."""
    descriptor = json.loads(payload)
    result = {
        "coverage": "partial",
        "sample_id": descriptor.get("sample_id"),
        "source_revision": descriptor.get("source_revision"),
        "created_at": descriptor.get("created_at"),
        "time_to_usable_seconds": None,
        "combined_effort_seconds": None,
        "resource_observations": [],
        "value_event_counts": {},
    }
    schema = f"r2s_demo_{_validate(session_id)}"
    table = tx.execute("SELECT to_regclass(?)", (f"{schema}.r2s_resource_usage",)).fetchone()
    if table and table[0] is not None:
        for (raw,) in tx.execute(f'SELECT payload FROM "{schema}".r2s_resource_usage').fetchall():
            usage = json.loads(raw)
            result["resource_observations"].append(
                {
                    key: usage.get(key)
                    for key in ("tool", "attempt_id", "outcome", "duration_seconds", "started_at", "completed_at")
                }
            )
        result["value_event_counts"] = dict(
            tx.execute(f'SELECT kind,COUNT(*) FROM "{schema}".r2s_value_events GROUP BY kind').fetchall()
        )
    return json.dumps(result, allow_nan=False)


def purge(settings: Settings) -> int:
    """Revoke expired capabilities before trying exclusive cleanup; retry closed rows."""
    from src.services.orchestration.samples.sessions import session_path

    now = datetime.now(UTC)
    idle_before = (now - timedelta(seconds=settings.product_demo_idle_seconds)).isoformat()
    database = RuntimeDatabase(settings.database_url)
    with database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_demo_sessions SET state='closed' WHERE state IN ('creating','open') "
            "AND (expires_at<=? OR (state='open' AND last_seen_at<=?))",
            (now.isoformat(), idle_before),
        )
        rows = tx.execute("SELECT session_id,payload FROM r2s_demo_sessions WHERE state='closed'").fetchall()
    removed = 0
    remote = artifact_remote(settings)
    if remote is None:
        return 0
    for session_id, payload in rows:
        _validate(session_id)
        try:
            with database.transaction(write=True) as tx:
                tx.execute("SET LOCAL lock_timeout='2s'")
                locked = tx.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(?,0))", (f"r2s.demo.session:{session_id}",)
                ).fetchone()
                if locked is None or not locked[0]:
                    continue
                # Preserve a truthful partial receipt independently of disposable runtime data.
                tx.execute(
                    "INSERT INTO r2s_demo_summaries(session_id,completed_at,payload) VALUES (?,?,?) "
                    "ON CONFLICT(session_id) DO NOTHING",
                    (session_id, now.isoformat(), _summary(tx, session_id, payload)),
                )
                tx.execute(f'DROP SCHEMA IF EXISTS "r2s_demo_{session_id}" CASCADE')
                prefix = output_prefix(settings, session_id) + "/"
                for item in remote.store.list_objects(prefix):
                    if not item.key.startswith(prefix):
                        raise ValueError("Object store returned an unrelated session key")
                    remote.store.delete(item.key)
                tx.execute("UPDATE r2s_demo_sessions SET state='purged',payload='{}' WHERE session_id=?", (session_id,))
            removed += 1
        except (OSError, ValueError, RuntimeError) as error:
            logger.warning("Demo cleanup deferred: %s", type(error).__name__)
    # Every host collects only its own cache after the durable namespace was removed.
    with database.transaction() as tx:
        purged = tx.execute("SELECT session_id FROM r2s_demo_sessions WHERE state='purged'").fetchall()
    for (session_id,) in purged:
        path = session_path(settings, session_id)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
    return removed
