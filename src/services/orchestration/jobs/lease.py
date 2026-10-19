"""Lease theo job cho attempt đang chạy (T-040, Q2).

Worker giữ lease trong suốt lượt chạy của job và gia hạn định kỳ. Lease hết hạn (worker đã trả pod, bị
giết vì quá thời gian) thì máy khác đưa job về FAILED retryable qua `recover_expired_leases`.

Fencing: khi attempt đang giữ lease, mọi revision job ghi qua `ProjectPersistence.save_job` chỉ commit
trong cùng transaction nếu lease còn của token này. Trainer còn sống trên host khác không ghi đè được.
"""

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from uuid import uuid4

from src.services.orchestration.gpu.state import claim_allowed
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction

#: Lease không được gia hạn trong mức này thì coi như worker đã mất.
LEASE_TTL = timedelta(minutes=10)
#: Chu kỳ gia hạn; nhỏ hơn TTL nhiều để vài lần lỗi DB thoáng qua không làm mất lease.
LEASE_RENEW_SECONDS = 60

logger = logging.getLogger(__name__)


@dataclass
class HeldLease:
    """Lease đang giữ cho một job; `lost` bật khi gia hạn thất bại (lease đã thuộc máy khác)."""

    job_id: str
    token: str
    lost: Event = field(default_factory=Event)


_ACTIVE: contextvars.ContextVar[HeldLease | None] = contextvars.ContextVar("r2s_active_job_lease", default=None)


def _stamp(moment: datetime) -> str:
    """Chuỗi thời gian cố định định dạng để so sánh thứ tự trực tiếp trong SQL."""
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def active_lease(job_id: str) -> HeldLease | None:
    held = _ACTIVE.get()
    return held if held is not None and held.job_id == job_id else None


def lease_lost(job_id: str) -> bool:
    """Attempt đang chạy job này đã mất lease: runner phải dừng tiến trình con."""
    held = active_lease(job_id)
    return held is not None and held.lost.is_set()


def fence(tx: RuntimeTransaction, job_id: str, *, now: datetime | None = None) -> None:
    """Gọi trong transaction ghi revision: lease của attempt hiện tại phải còn, nếu không thì không ghi."""
    held = active_lease(job_id)
    if held is None:
        return
    row = tx.execute("SELECT lease_token, lease_expires_at FROM r2s_job_leases WHERE job_id=?", (job_id,)).fetchone()
    current = _stamp(now or datetime.now(UTC))
    if row is None or row[0] != held.token or row[1] <= current:
        held.lost.set()
        raise RuntimeStateConflictError("Lease của attempt đã mất; revision không được ghi")


def acquire(
    database: RuntimeDatabase,
    job_id: str,
    worker_id: str,
    *,
    now: datetime | None = None,
    ttl: timedelta = LEASE_TTL,
) -> HeldLease | None:
    """Giữ lease job nếu chưa ai giữ hoặc lease cũ đã hết hạn; None nếu worker khác còn giữ."""
    current = now or datetime.now(UTC)
    held = HeldLease(job_id=job_id, token=uuid4().hex)
    with database.transaction(write=True) as tx:
        if not claim_allowed(tx, "pipeline", mark_busy=True):
            return None
        changed = tx.execute(
            "INSERT INTO r2s_job_leases(job_id, lease_token, worker_id, lease_expires_at) VALUES (?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET lease_token=excluded.lease_token, worker_id=excluded.worker_id, "
            "lease_expires_at=excluded.lease_expires_at WHERE r2s_job_leases.lease_expires_at <= ?",
            (job_id, held.token, worker_id, _stamp(current + ttl), _stamp(current)),
        ).rowcount
    return held if changed else None


def renew(
    database: RuntimeDatabase, held: HeldLease, *, now: datetime | None = None, ttl: timedelta = LEASE_TTL
) -> bool:
    """Kéo dài lease của chính token này; False khi lease đã đổi chủ hoặc đã hết hạn."""
    current = now or datetime.now(UTC)
    with database.transaction(write=True) as tx:
        changed = tx.execute(
            "UPDATE r2s_job_leases SET lease_expires_at=? WHERE job_id=? AND lease_token=? AND lease_expires_at > ?",
            (_stamp(current + ttl), held.job_id, held.token, _stamp(current)),
        ).rowcount
    return bool(changed)


def release(database: RuntimeDatabase, held: HeldLease) -> None:
    with database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_job_leases WHERE job_id=? AND lease_token=?", (held.job_id, held.token))


def expired_job_ids(database: RuntimeDatabase, *, now: datetime | None = None) -> list[str]:
    current = _stamp(now or datetime.now(UTC))
    with database.transaction() as tx:
        rows = tx.execute("SELECT job_id FROM r2s_job_leases WHERE lease_expires_at <= ?", (current,)).fetchall()
    return [row[0] for row in rows]


def release_expired(database: RuntimeDatabase, job_id: str, *, now: datetime | None = None) -> None:
    """Xoá lease đã hết hạn của job (sau khi đã xử lý); lease còn hạn của máy khác không bị đụng tới."""
    current = _stamp(now or datetime.now(UTC))
    with database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_job_leases WHERE job_id=? AND lease_expires_at <= ?", (job_id, current))


@contextmanager
def leased(
    database: RuntimeDatabase,
    job_id: str,
    worker_id: str,
    *,
    renew_every: float = LEASE_RENEW_SECONDS,
    ttl: timedelta = LEASE_TTL,
) -> Iterator[HeldLease | None]:
    """Giữ lease trong khối lệnh; yield None khi worker khác đang giữ job."""
    held = acquire(database, job_id, worker_id, ttl=ttl)
    if held is None:
        yield None
        return
    stop = Event()

    def keep_alive() -> None:
        while not stop.wait(renew_every):
            try:
                if not renew(database, held, ttl=ttl):
                    held.lost.set()
                    logger.warning("Mất lease job %s; attempt sẽ dừng tiến trình con", job_id)
                    return
            except Exception as error:  # noqa: BLE001 - lỗi DB thoáng qua: thử lại chu kỳ sau; hết hạn thì fence chặn ghi
                logger.warning("Không gia hạn được lease job %s: %s", job_id, type(error).__name__)

    Thread(target=keep_alive, name=f"lease-{job_id}", daemon=True).start()
    token = _ACTIVE.set(held)
    try:
        yield held
    finally:
        _ACTIVE.reset(token)
        stop.set()
        try:
            release(database, held)
        except Exception as error:  # noqa: BLE001 - lease tự hết hạn; không để lỗi dọn dẹp che lỗi chính
            logger.warning("Không trả được lease job %s: %s", job_id, type(error).__name__)
