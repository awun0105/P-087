"""Durable Guest run quota and actor-scoped idempotency ledger."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.services.orchestration.auth.quota import (
    GUEST_QUOTA_LIMIT,
    GuestQuotaSummary,
    guest_quota_window,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction

QuotaOperation = Literal["job.create", "scene.create", "job.retry"]


class GuestQuotaIntent(BaseModel):
    """Validated identity and fingerprint for one user-initiated Guest run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_user_id: str = Field(min_length=1)
    operation_kind: QuotaOperation
    idempotency_key: str = Field(min_length=1, max_length=200)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class GuestQuotaIntentResult(BaseModel):
    """Durable result identity; replay never creates another job or charge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    replayed: bool
    result_kind: Literal["job"]
    result_id: str = Field(min_length=1)
    result_reference: str = Field(min_length=1)


class GuestQuotaExceededError(RuntimeError):
    """Raised inside the acceptance transaction; the caller returns its stable 429."""

    def __init__(self, summary: GuestQuotaSummary) -> None:
        super().__init__("Guest daily job quota exceeded")
        self.summary = summary


class GuestQuotaIdempotencyConflictError(RuntimeStateConflictError):
    """An actor reused an operation key with a different canonical request."""


def guest_quota_intent_result(tx: RuntimeTransaction, intent: GuestQuotaIntent) -> GuestQuotaIntentResult | None:
    """Read an accepted intent, rejecting a key whose request fingerprint changed."""
    row = tx.execute(
        "SELECT request_fingerprint, result_kind, result_id, result_reference FROM r2s_quota_intents "
        "WHERE actor_user_id=? AND operation_kind=? AND idempotency_key=?",
        (intent.actor_user_id, intent.operation_kind, intent.idempotency_key),
    ).fetchone()
    if row is None:
        return None
    if row[0] != intent.request_fingerprint:
        raise GuestQuotaIdempotencyConflictError("Idempotency-Key đã được dùng với request khác")
    if row[1] != "job":
        raise RuntimeError("Quota intent references an unsupported result kind")
    return GuestQuotaIntentResult(replayed=True, result_kind="job", result_id=str(row[2]), result_reference=str(row[3]))


def lookup_guest_quota_intent(database: RuntimeDatabase, intent: GuestQuotaIntent) -> GuestQuotaIntentResult | None:
    """Read a committed intent before route validation or artifact publication."""
    with database.transaction() as tx:
        return guest_quota_intent_result(tx, intent)


def guest_quota_summary(
    database: RuntimeDatabase, actor_user_id: str, now: datetime | None = None
) -> GuestQuotaSummary:
    """Read the current Vietnam calendar window; an unseen day starts at zero."""
    window = guest_quota_window(now)
    with database.transaction() as tx:
        row = tx.execute(
            "SELECT resets_at_utc, policy_limit, used_count FROM r2s_guest_quota_windows "
            "WHERE actor_user_id=? AND policy_id=? AND window_start_utc=?",
            (actor_user_id, window.policy_id, window.window_start_utc.isoformat()),
        ).fetchone()
    used = 0
    if row is not None:
        if row[0] != window.resets_at_utc.isoformat() or int(row[1]) != GUEST_QUOTA_LIMIT:
            raise RuntimeError("Persisted Guest quota window differs from the active policy")
        used = int(row[2])
    return GuestQuotaSummary(
        policy_id=window.policy_id,
        limit=window.limit,
        timezone=window.timezone,
        window_start_utc=window.window_start_utc,
        resets_at_utc=window.resets_at_utc,
        used=used,
        remaining=max(window.limit - used, 0),
    )


def accept_guest_quota_intent(
    tx: RuntimeTransaction,
    intent: GuestQuotaIntent,
    *,
    result_kind: Literal["job"],
    result_id: str,
    result_reference: str,
    now: datetime | None = None,
) -> GuestQuotaIntentResult:
    """Reserve one Guest run within the caller's job/project transaction.

    SQLite serializes this writer with ``BEGIN IMMEDIATE``. PostgreSQL locks the
    calendar row, then uses the idempotency unique key to arbitrate retries that
    cross a midnight boundary.
    """
    existing = guest_quota_intent_result(tx, intent)
    if existing is not None:
        return existing

    accepted_at = now or datetime.now(UTC)
    if accepted_at.tzinfo is None or accepted_at.utcoffset() is None:
        raise ValueError("Quota acceptance clock must be timezone-aware")
    accepted_at = accepted_at.astimezone(UTC)
    window = guest_quota_window(accepted_at)
    tx.execute(
        "INSERT INTO r2s_guest_quota_windows "
        "(actor_user_id, policy_id, window_start_utc, resets_at_utc, policy_limit, used_count) "
        "VALUES (?, ?, ?, ?, ?, 0) ON CONFLICT(actor_user_id, policy_id, window_start_utc) DO NOTHING",
        (
            intent.actor_user_id,
            window.policy_id,
            window.window_start_utc.isoformat(),
            window.resets_at_utc.isoformat(),
            window.limit,
        ),
    )
    row = tx.execute(
        "SELECT resets_at_utc, policy_limit, used_count FROM r2s_guest_quota_windows "
        "WHERE actor_user_id=? AND policy_id=? AND window_start_utc=?" + tx.lock_suffix(),
        (intent.actor_user_id, window.policy_id, window.window_start_utc.isoformat()),
    ).fetchone()
    if row is None:
        raise RuntimeError("Guest quota window disappeared during acceptance")
    if row[0] != window.resets_at_utc.isoformat() or int(row[1]) != GUEST_QUOTA_LIMIT:
        raise RuntimeError("Persisted Guest quota window differs from the active policy")
    existing = guest_quota_intent_result(tx, intent)
    if existing is not None:
        return existing
    used = int(row[2])
    inserted = tx.execute(
        "INSERT INTO r2s_quota_intents "
        "(actor_user_id, operation_kind, idempotency_key, policy_id, window_start_utc, "
        "request_fingerprint, accepted_at_utc, result_kind, result_id, result_reference) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(actor_user_id, operation_kind, idempotency_key) DO NOTHING",
        (
            intent.actor_user_id,
            intent.operation_kind,
            intent.idempotency_key,
            window.policy_id,
            window.window_start_utc.isoformat(),
            intent.request_fingerprint,
            accepted_at.isoformat(),
            result_kind,
            result_id,
            result_reference,
        ),
    )
    if inserted.rowcount != 1:
        # A concurrent request using the same key may have crossed midnight and
        # therefore locked a different quota window. The unique key is final.
        existing = guest_quota_intent_result(tx, intent)
        if existing is None:
            raise RuntimeError("Quota idempotency conflict had no committed intent")
        return existing

    if used >= window.limit:
        raise GuestQuotaExceededError(
            GuestQuotaSummary(
                policy_id=window.policy_id,
                limit=window.limit,
                timezone=window.timezone,
                window_start_utc=window.window_start_utc,
                resets_at_utc=window.resets_at_utc,
                used=used,
                remaining=0,
            )
        )

    updated = tx.execute(
        "UPDATE r2s_guest_quota_windows SET used_count=used_count+1 "
        "WHERE actor_user_id=? AND policy_id=? AND window_start_utc=? AND used_count < policy_limit",
        (intent.actor_user_id, window.policy_id, window.window_start_utc.isoformat()),
    )
    if updated.rowcount != 1:
        raise GuestQuotaExceededError(
            GuestQuotaSummary(
                policy_id=window.policy_id,
                limit=window.limit,
                timezone=window.timezone,
                window_start_utc=window.window_start_utc,
                resets_at_utc=window.resets_at_utc,
                used=min(max(used + 1, window.limit), window.limit),
                remaining=0,
            )
        )
    return GuestQuotaIntentResult(
        replayed=False, result_kind=result_kind, result_id=result_id, result_reference=result_reference
    )
