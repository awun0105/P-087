from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.models.contracts.validation_run import ValidationRunStatus
from src.services.orchestration.review.validation_queue import ValidationQueue
from tests.test_orchestration.test_review_workflow import _packaged
from tests.test_orchestration.test_validation_queue import _config, _profile


def _guest():
    from src.services.orchestration.auth import UserRecord

    return UserRecord(
        user_id="u-guest",
        email="guest@example.com",
        display_name="Guest User",
        role="guest",
        password_hash="test-only",
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    from src.api import auth
    from src.api.studio import deps
    from src.main import app

    registry, job, candidate_checksum = _packaged(tmp_path)
    policy = _config()
    profile = _profile(registry.runtime_resolver)
    policy_path = tmp_path / "isaac-validation-policy.json"
    profile_path = tmp_path / "isaac-validation-profile.json"
    policy_path.write_text(policy.model_dump_json(indent=2), encoding="utf-8")
    profile_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    settings = Settings(
        _env_file=None,
        openai_api_key="test-only",
        auth_required=True,
        product_isaac_validation_config=policy_path,
        product_isaac_validation_profile=profile_path,
    )
    user = _guest()
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "current_user", lambda request: user)
    monkeypatch.setattr(registry, "get_job_owner_user_id", lambda job_id: user.user_id)
    client = TestClient(app)
    return SimpleNamespace(
        client=client,
        registry=registry,
        job=job.job_id,
        candidate_checksum=candidate_checksum,
        settings=settings,
        policy_path=policy_path,
        profile_path=profile_path,
    )


def test_guest_can_submit_and_read_only_own_durable_validation_runs(setup) -> None:  # noqa: ANN001
    url = f"/api/v1/jobs/{setup.job}/validation-runs"
    body = {"candidate_checksum": setup.candidate_checksum}
    headers = {"Idempotency-Key": "guest-validation-001"}

    accepted = setup.client.post(url, json=body, headers=headers)
    replayed = setup.client.post(url, json=body, headers=headers)

    assert accepted.status_code == 202, accepted.text
    assert replayed.status_code == 202, replayed.text
    assert replayed.json()["run_id"] == accepted.json()["run_id"]
    assert setup.client.get(url).json()[0]["run_id"] == accepted.json()["run_id"]
    assert (
        setup.client.get(f"{url}/{accepted.json()['run_id']}").json()["candidate_checksum"] == setup.candidate_checksum
    )


def test_validation_api_fails_closed_without_server_policy_or_runtime_profile(setup, monkeypatch) -> None:  # noqa: ANN001
    from src.api.studio import deps

    unconfigured = setup.settings.model_copy(
        update={"product_isaac_validation_config": None, "product_isaac_validation_profile": None}
    )
    monkeypatch.setattr(deps, "get_settings", lambda: unconfigured)

    response = setup.client.post(
        f"/api/v1/jobs/{setup.job}/validation-runs",
        json={"candidate_checksum": setup.candidate_checksum},
        headers={"Idempotency-Key": "unconfigured-validation"},
    )

    assert response.status_code == 409
    assert "PRODUCT_ISAAC_VALIDATION_CONFIG" in response.json()["detail"]


def test_guest_cannot_read_or_mutate_another_users_validation_runs(setup, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(setup.registry, "get_job_owner_user_id", lambda job_id: "u-other-guest")
    url = f"/api/v1/jobs/{setup.job}/validation-runs"

    assert setup.client.get(url).status_code == 403
    assert (
        setup.client.post(
            url,
            json={"candidate_checksum": setup.candidate_checksum},
            headers={"Idempotency-Key": "cross-owner-validation"},
        ).status_code
        == 403
    )


def test_stale_candidate_is_rejected_and_queued_attempt_can_be_cancelled(setup) -> None:  # noqa: ANN001
    url = f"/api/v1/jobs/{setup.job}/validation-runs"
    stale = setup.client.post(
        url,
        json={"candidate_checksum": "sha256:" + "f" * 64},
        headers={"Idempotency-Key": "stale-validation"},
    )
    assert stale.status_code == 409

    accepted = setup.client.post(
        url,
        json={"candidate_checksum": setup.candidate_checksum},
        headers={"Idempotency-Key": "cancel-validation"},
    )
    assert accepted.status_code == 202, accepted.text
    cancelled = setup.client.post(f"{url}/{accepted.json()['run_id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == ValidationRunStatus.CANCELLED


def test_retry_endpoint_reuses_bound_profile_only_for_retryable_failure(setup) -> None:  # noqa: ANN001
    url = f"/api/v1/jobs/{setup.job}/validation-runs"
    accepted = setup.client.post(
        url,
        json={"candidate_checksum": setup.candidate_checksum},
        headers={"Idempotency-Key": "retry-validation-original"},
    )
    assert accepted.status_code == 202, accepted.text
    queue = ValidationQueue(setup.registry.persistence.database, setup.registry.runtime_resolver)
    claim = queue.claim_next("test-worker")
    assert claim is not None
    queue.start(claim, current_candidate_checksum=setup.candidate_checksum)
    queue.fail(claim, error_code="WORKER_LEASE_EXPIRED", retryable=True)

    retried = setup.client.post(
        f"{url}/{accepted.json()['run_id']}/retry",
        headers={"Idempotency-Key": "retry-validation-next"},
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["attempt"] == accepted.json()["attempt"] + 1
    assert retried.json()["validation_config_checksum"] == accepted.json()["validation_config_checksum"]
