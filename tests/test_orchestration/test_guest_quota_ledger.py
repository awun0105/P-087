"""Durable Guest calendar quota: idempotency, rollback, midnight and writer races."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.services.orchestration.auth import AuthService
from src.services.orchestration.auth.quota_ledger import (
    GuestQuotaExceededError,
    GuestQuotaIdempotencyConflictError,
    GuestQuotaIntent,
    accept_guest_quota_intent,
    guest_quota_summary,
    lookup_guest_quota_intent,
)
from src.services.orchestration.jobs.database import RuntimeDatabase


def _intent(
    actor_user_id: str,
    key: str,
    payload: dict[str, object] | None = None,
    *,
    operation: str = "job.create",
) -> GuestQuotaIntent:
    request = payload or {"project_id": "project-a"}
    fingerprint = hashlib.sha256(
        json.dumps({"operation": operation, "payload": request}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return GuestQuotaIntent(
        actor_user_id=actor_user_id,
        operation_kind=operation,  # type: ignore[arg-type]
        idempotency_key=key,
        request_fingerprint=fingerprint,
    )


def _accept(
    database: RuntimeDatabase,
    intent: GuestQuotaIntent,
    result_id: str,
    *,
    now: datetime | None = None,
):
    with database.transaction(write=True) as tx:
        return accept_guest_quota_intent(
            tx,
            intent,
            result_kind="job",
            result_id=result_id,
            result_reference=f"artifact://jobs/{result_id}/accepted-manifest.json",
            now=now,
        )


def _database(url: str) -> tuple[RuntimeDatabase, str]:
    database = RuntimeDatabase(url)
    user = AuthService(database).create_user(f"guest-{uuid4().hex}@example.com", "Guest", "mat-khau-du-dai", "guest")
    return database, user.user_id


def test_guest_quota_same_key_replays_original_acceptance(runtime_database_url: str) -> None:
    database, user_id = _database(runtime_database_url)
    intent = _intent(user_id, "same-request")

    first = _accept(database, intent, "job-original")
    replay = _accept(database, intent, "job-should-not-exist")

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.result_id == first.result_id == "job-original"
    assert replay.result_reference == first.result_reference
    assert guest_quota_summary(database, user_id).used == 1


def test_guest_quota_same_key_different_fingerprint_conflicts_without_charge(runtime_database_url: str) -> None:
    database, user_id = _database(runtime_database_url)
    _accept(database, _intent(user_id, "reused", {"project_id": "project-a"}), "job-a")

    with pytest.raises(GuestQuotaIdempotencyConflictError):
        _accept(database, _intent(user_id, "reused", {"project_id": "project-b"}), "job-b")

    assert guest_quota_summary(database, user_id).used == 1
    with database.transaction() as tx:
        assert tx.execute("SELECT result_id FROM r2s_quota_intents").fetchall() == [("job-a",)]


def test_guest_quota_failed_acceptance_transaction_rolls_back_intent_and_counter(runtime_database_url: str) -> None:
    database, user_id = _database(runtime_database_url)
    intent = _intent(user_id, "rollback")

    with pytest.raises(RuntimeError, match="simulated CAS failure"):
        with database.transaction(write=True) as tx:
            accept_guest_quota_intent(
                tx,
                intent,
                result_kind="job",
                result_id="job-rollback",
                result_reference="artifact://jobs/job-rollback/manifest.json",
            )
            raise RuntimeError("simulated CAS failure")

    assert guest_quota_summary(database, user_id).used == 0
    assert lookup_guest_quota_intent(database, intent) is None


def test_guest_quota_rolls_at_vietnam_midnight_and_old_key_does_not_charge_new_day(runtime_database_url: str) -> None:
    database, user_id = _database(runtime_database_url)
    before_midnight = datetime(2026, 10, 8, 16, 59, tzinfo=UTC)
    after_midnight = before_midnight + timedelta(minutes=2)
    intent = _intent(user_id, "cross-midnight")

    _accept(database, intent, "job-first", now=before_midnight)
    replay = _accept(database, intent, "job-second", now=after_midnight)
    assert replay.replayed is True and replay.result_id == "job-first"
    assert guest_quota_summary(database, user_id, after_midnight).used == 0

    _accept(database, _intent(user_id, "next-day"), "job-next-day", now=after_midnight)
    assert guest_quota_summary(database, user_id, after_midnight).used == 1


def test_guest_quota_concurrent_writers_accept_exactly_three(runtime_database_url: str) -> None:
    database, user_id = _database(runtime_database_url)

    def submit(index: int) -> str:
        try:
            result = _accept(database, _intent(user_id, f"parallel-{index}"), f"job-{index}")
        except GuestQuotaExceededError:
            return "429"
        return "accepted" if not result.replayed else "replayed"

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(submit, range(4)))

    assert outcomes.count("accepted") == 3
    assert outcomes.count("429") == 1
    assert guest_quota_summary(database, user_id).used == 3
    with database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_quota_intents").fetchone() == (3,)
