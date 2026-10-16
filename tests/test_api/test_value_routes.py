"""Route nhận sự kiện giá trị: quyền sở hữu, năm luật từ chối 422 và actor lấy từ người đăng nhập (§15.3)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from src.api import auth as auth_api
from src.api.studio import deps
from src.api.studio import value as value_api
from src.main import app
from src.services.orchestration.auth import Actor, UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects import ProjectRegistry
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.value import list_events

_OPERATOR = "/api/v1/jobs/{job_id}/value-events/operator-time"
_WALK = "/api/v1/jobs/{job_id}/value-events/walk-session"


def _user(role: str, user_id: str | None = None) -> UserRecord:
    return UserRecord(
        user_id=user_id or f"user-{role}",
        email=f"{role}@example.com",
        display_name=role.title(),
        role=role,  # type: ignore[arg-type]
        password_hash="test-only-hash",
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    url = f"sqlite:///{tmp_path / 'runtime.db'}"
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=RuntimeDatabase(url))
    registry.seed_from_fixtures()
    owner = _user("guest", "user-owner")
    job = registry.create_job(
        JobCreateInput(project_id="project-fixture-001"),
        requested_by=Actor(user_id=owner.user_id, display_name=owner.display_name, role=owner.role),
        owner_user_id=owner.user_id,
    )
    monkeypatch.setattr(deps, "registry", lambda: registry)
    monkeypatch.setattr(deps, "settings", lambda: SimpleNamespace(database_url=url))
    return SimpleNamespace(url=url, registry=registry, job_id=job.job_id, database=RuntimeDatabase(url))


@pytest.fixture
def as_user():  # noqa: ANN201 - trả hàm đặt người gọi cho một request
    original = app.dependency_overrides.copy()

    def set_user(user: UserRecord | None) -> None:
        app.dependency_overrides[auth_api.require_contributor] = lambda: user

    yield set_user
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _batch(start_offset: int, end_offset: int, **overrides: object) -> dict:
    now = datetime.now(UTC)
    body = {
        "session_key": "session-abcdef12",
        "surface": "studio",
        "started_at": (now - timedelta(seconds=start_offset)).isoformat(),
        "ended_at": (now - timedelta(seconds=end_offset)).isoformat(),
        "active_seconds": 30,
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_owner_records_operator_time_with_actor_from_the_session(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:
    as_user(_user("guest", "user-owner"))

    response = await client.post(
        _OPERATOR.format(job_id=world.job_id),
        json=_batch(120, 60, actor_id="someone-else"),
    )

    assert response.status_code == 204
    (event,) = list_events(world.database, world.job_id, {"operator_time"})
    assert event.actor_id == "user-owner"
    assert event.payload["surface"] == "studio"
    assert event.payload["active_seconds"] == 30


@pytest.mark.asyncio
async def test_guest_cannot_record_time_on_a_foreign_job(client: AsyncClient, world: SimpleNamespace, as_user) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-other"))

    response = await client.post(_OPERATOR.format(job_id=world.job_id), json=_batch(120, 60))
    walk = await client.post(
        _WALK.format(job_id=world.job_id),
        json={
            "scene_revision": "rev-001",
            "started_at": _batch(120, 60)["started_at"],
            "ended_at": _batch(120, 60)["ended_at"],
            "outcome": "completed",
        },
    )

    assert response.status_code == 403
    assert walk.status_code == 403
    assert list_events(world.database, world.job_id) == []


@pytest.mark.asyncio
async def test_unknown_job_is_404(client: AsyncClient, world: SimpleNamespace, as_user) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-owner"))

    response = await client.post(_OPERATOR.format(job_id="job-missing"), json=_batch(120, 60))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected_when_auth_is_required(
    client: AsyncClient, world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth_api,
        "settings",
        lambda: SimpleNamespace(auth_required=True, database_url=world.url, auth_session_days=1, auth_invite_days=1),
    )
    original = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    try:
        response = await client.post(_OPERATOR.format(job_id=world.job_id), json=_batch(120, 60))
    finally:
        app.dependency_overrides.update(original)

    assert response.status_code == 401
    assert list_events(world.database, world.job_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "start", "end"),
    [
        ({}, 60, 60),  # ended_at ≤ started_at
        ({}, 400, 60),  # dài hơn 300 giây
        ({"active_seconds": 61}, 120, 60),  # active lớn hơn khoảng thời gian (60 giây)
        ({"active_seconds": -1}, 120, 60),  # active âm
        ({}, 20, -300),  # lệch tương lai hơn 60 giây
    ],
)
async def test_operator_batches_violating_the_rules_are_rejected(
    client: AsyncClient,
    world: SimpleNamespace,
    as_user,  # noqa: ANN001
    overrides: dict,
    start: int,
    end: int,
) -> None:
    as_user(_user("guest", "user-owner"))

    response = await client.post(_OPERATOR.format(job_id=world.job_id), json=_batch(start, end, **overrides))

    assert response.status_code == 422
    assert list_events(world.database, world.job_id) == []


@pytest.mark.asyncio
async def test_operator_batch_overlapping_the_previous_batch_of_the_same_session_is_rejected(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-owner"))
    first = await client.post(_OPERATOR.format(job_id=world.job_id), json=_batch(300, 200))
    overlapping = await client.post(_OPERATOR.format(job_id=world.job_id), json=_batch(250, 150))
    other_session = await client.post(
        _OPERATOR.format(job_id=world.job_id), json=_batch(250, 150, session_key="session-zzzzzz99")
    )

    assert first.status_code == 204
    assert overlapping.status_code == 422
    assert other_session.status_code == 204
    assert len(list_events(world.database, world.job_id, {"operator_time"})) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (60, 60),  # ended_at ≤ started_at
        (60 * 60 * 3, 60),  # dài hơn 2 giờ
        (120, -300),  # lệch tương lai hơn 60 giây
    ],
)
async def test_walk_sessions_violating_the_rules_are_rejected(
    client: AsyncClient,
    world: SimpleNamespace,
    as_user,  # noqa: ANN001
    start: int,
    end: int,
) -> None:
    as_user(_user("guest", "user-owner"))
    window = _batch(start, end)

    response = await client.post(
        _WALK.format(job_id=world.job_id),
        json={
            "scene_revision": "rev-001",
            **{k: window[k] for k in ("started_at", "ended_at")},
            "outcome": "completed",
        },
    )

    assert response.status_code == 422
    assert list_events(world.database, world.job_id) == []


@pytest.mark.asyncio
async def test_completed_walk_session_is_recorded(client: AsyncClient, world: SimpleNamespace, as_user) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-owner"))
    window = _batch(900, 600)

    response = await client.post(
        _WALK.format(job_id=world.job_id),
        json={"scene_revision": "rev-002", **{k: window[k] for k in ("started_at", "ended_at")}, "outcome": "aborted"},
    )

    assert response.status_code == 204
    (event,) = list_events(world.database, world.job_id, {"walk_session"})
    assert event.actor_id == "user-owner"
    assert event.payload["scene_revision"] == "rev-002"
    assert event.payload["outcome"] == "aborted"


@pytest.mark.asyncio
async def test_failed_event_write_still_returns_no_content(
    client: AsyncClient, world: SimpleNamespace, as_user, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-owner"))

    class WriteFailingDatabase:
        """Đọc vẫn được (kiểm chồng lô), chỉ ghi nhật ký lỗi."""

        def transaction(self, *, write: bool = False):  # noqa: ANN201 - test double
            if write:
                raise sqlite3.OperationalError("disk I/O error")
            return world.database.transaction(write=write)

    monkeypatch.setattr(value_api, "_database", WriteFailingDatabase)

    response = await client.post(_OPERATOR.format(job_id=world.job_id), json=_batch(120, 60))

    assert response.status_code == 204
