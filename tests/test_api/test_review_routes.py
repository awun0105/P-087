"""API duyệt/phát hành: chỉ Reviewer đã đăng nhập (fail closed kể cả khi tắt AUTH_REQUIRED)."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.auth import UserRecord
from src.services.orchestration.review.workflow import record_validation_report, review_state
from tests.test_orchestration.test_review_workflow import _install_worker_run, _packaged, _report


def _user(role: str) -> UserRecord:
    return UserRecord(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        display_name=role,
        role=role,
        password_hash="x",
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    from src.api import auth
    from src.api.studio import deps
    from src.main import app

    registry, job, candidate = _packaged(tmp_path)
    report = _report(candidate)
    _install_worker_run(registry, job, review_state(registry, job.job_id).package, report)
    audits: list[tuple] = []
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    service = SimpleNamespace(
        audit=lambda *args: audits.append(args),
        get_user=lambda user_id: _user("reviewer") if user_id == "u-reviewer" else None,
    )
    monkeypatch.setattr(auth, "auth_service", lambda: service)
    body = {
        "decision": "APPROVE",
        "candidate_checksum": candidate,
        "validation_report_checksum": report.report_checksum,
        "accepted_warning_ids": [],
    }
    return SimpleNamespace(
        client=TestClient(app),
        job=job.job_id,
        body=body,
        audits=audits,
        auth=auth,
        registry=registry,
        candidate_checksum=candidate,
        report=report,
    )


def test_decision_requires_logged_in_reviewer(setup, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    url = f"/api/v1/jobs/{setup.job}/review-decision"
    monkeypatch.setattr(setup.auth, "current_user", lambda request: None)
    assert setup.client.post(url, json=setup.body).status_code == 401
    monkeypatch.setattr(setup.auth, "current_user", lambda request: _user("editor"))
    assert setup.client.post(url, json=setup.body).status_code == 403
    assert setup.client.get(f"/api/v1/jobs/{setup.job}/review-state").json()["record"]["status"] == "READY_FOR_REVIEW"


def test_reviewer_approves_and_downloads_release(setup, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(setup.auth, "current_user", lambda request: _user("reviewer"))
    response = setup.client.post(f"/api/v1/jobs/{setup.job}/review-decision", json=setup.body)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["record"]["status"] == "RELEASED" and state["approval"]["reviewer_id"] == "u-reviewer"
    assert state["reviewer_name"] == "reviewer"  # UI hiện tên người duyệt, không chỉ id
    assert setup.client.get(f"/api/v1/jobs/{setup.job}/review-state").json()["reviewer_name"] == "reviewer"
    assert setup.audits and setup.audits[0][1] == "review.approve"
    download = setup.client.get(f"/api/v1/jobs/{setup.job}/release-download")
    assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
    again = setup.client.post(f"/api/v1/jobs/{setup.job}/review-decision", json=setup.body)
    assert again.status_code == 409


def test_legacy_report_cannot_claim_isaac_version_or_enable_review_api(setup, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(setup.auth, "current_user", lambda request: _user("reviewer"))
    database = setup.registry.persistence.database
    with database.transaction(write=True) as tx:
        tx.execute(
            "DELETE FROM r2s_validation_selections WHERE job_id=? AND candidate_checksum=?",
            (setup.job, setup.candidate_checksum),
        )

    draft = setup.report.model_copy(
        update={"environment_versions": {"isaac_sim": "4.2.0"}, "report_checksum": "sha256:" + "0" * 64}
    )
    legacy = draft.model_copy(update={"report_checksum": canonical_content_checksum(draft, "report_checksum")})
    record_validation_report(setup.registry, setup.job, legacy)

    state = setup.client.get(f"/api/v1/jobs/{setup.job}/review-state").json()
    assert state["record"]["status"] == "CANDIDATE_READY"
    assert state["isaac_runtime_proof"] is False
    assert state["validation"]["environment_versions"]["isaac_sim"] == "4.2.0"
    assert state["blockers"]

    body = {**setup.body, "validation_report_checksum": legacy.report_checksum}
    response = setup.client.post(f"/api/v1/jobs/{setup.job}/review-decision", json=body)
    assert response.status_code == 409


def test_stale_candidate_decision_is_rejected_by_api(setup, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(setup.auth, "current_user", lambda request: _user("reviewer"))
    body = {**setup.body, "candidate_checksum": "sha256:" + "0" * 64}
    response = setup.client.post(f"/api/v1/jobs/{setup.job}/review-decision", json=body)
    assert response.status_code == 409
