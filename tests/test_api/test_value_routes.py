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
from src.services.orchestration.value.ground_truth import BenchmarkTruth, write_truth

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
    monkeypatch.setattr(deps, "settings", lambda: SimpleNamespace(database_url=url, benchmark_gpu_hourly_usd=None))
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


_TRUTH = "/api/v1/jobs/{job_id}/benchmark-truth"
_SCENE_JOB = "job-fixture-001"  # job seed có SceneIR thật, dùng để kiểm revision và vật cản


def _truth_body(expected_version: int, **truth: object) -> dict:
    body = {"include_in_benchmark": True, "notes": "bản thử"}
    body.update(truth)
    return {"expected_version": expected_version, "truth": body}


@pytest.mark.asyncio
async def test_missing_truth_reads_as_version_zero_not_404(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-owner"))

    response = await client.get(_TRUTH.format(job_id=world.job_id))

    assert response.status_code == 200
    assert response.json()["version"] == 0
    assert response.json()["updated_at"] is None
    assert response.json()["truth"]["include_in_benchmark"] is False


@pytest.mark.asyncio
async def test_truth_write_is_cas_and_read_back_matches(client: AsyncClient, world: SimpleNamespace, as_user) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-owner"))
    url = _TRUTH.format(job_id=world.job_id)

    written = await client.put(url, json=_truth_body(0, notes="lần đầu"))
    stale = await client.put(url, json=_truth_body(0, notes="ghi muộn"))
    read = await client.get(url)

    assert written.status_code == 200 and written.json()["version"] == 1
    assert stale.status_code == 409
    assert read.json()["version"] == 1
    assert read.json()["truth"]["notes"] == "lần đầu"
    assert read.json()["updated_at"] is not None


@pytest.mark.asyncio
async def test_unknown_revision_and_missing_obstacle_are_422_with_the_wrong_item(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    # Job có scene thật là job-fixture-001 (seed, không có chủ sở hữu): gọi không đăng nhập như workspace cục bộ.
    as_user(None)
    url = _TRUTH.format(job_id=_SCENE_JOB)

    bad_layout = await client.put(
        url,
        json=_truth_body(
            0,
            layouts={"A": {"scene_revision": "rev-khong-co", "tagged_at": "2026-10-16T08:00:00+00:00"}},
        ),
    )
    bad_obstacle = await client.put(url, json=_truth_body(0, key_obstacle_ids=["vat-khong-co"]))

    assert bad_layout.status_code == 422
    assert "layout A" in bad_layout.json()["detail"] and "rev-khong-co" in bad_layout.json()["detail"]
    assert bad_obstacle.status_code == 422
    assert "vat-khong-co" in bad_obstacle.json()["detail"]


@pytest.mark.asyncio
async def test_existing_revision_and_object_pass_the_reference_check(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(None)
    scene = world.registry.scene.current(_SCENE_JOB).scene
    obstacle = scene.objects[0].id
    layout = {"scene_revision": scene.scene_revision, "tagged_at": "2026-10-16T08:00:00+00:00"}

    response = await client.put(
        _TRUTH.format(job_id=_SCENE_JOB),
        json=_truth_body(0, layouts={"A": layout}, key_obstacle_ids=[obstacle]),
    )

    assert response.status_code == 200
    assert response.json()["truth"]["key_obstacle_ids"] == [obstacle]


@pytest.mark.asyncio
async def test_foreign_guest_can_read_but_not_write_the_truth(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-other"))
    url = _TRUTH.format(job_id=world.job_id)

    read = await client.get(url)
    write = await client.put(url, json=_truth_body(0))

    assert read.status_code == 200
    assert write.status_code == 403


@pytest.mark.asyncio
async def test_truth_routes_return_404_for_an_unknown_job(client: AsyncClient, world: SimpleNamespace, as_user) -> None:  # noqa: ANN001
    as_user(_user("guest", "user-owner"))

    assert (await client.get(_TRUTH.format(job_id="job-missing"))).status_code == 404
    assert (await client.put(_TRUTH.format(job_id="job-missing"), json=_truth_body(0))).status_code == 404


@pytest.mark.asyncio
async def test_layout_tag_time_is_set_by_the_server_and_kept_while_the_revision_is_unchanged(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    """P3 so mốc gắn layout với giờ máy chủ của sự kiện: đồng hồ trình duyệt (ở đây lệch về năm 2001) không được dùng."""
    as_user(None)
    url = _TRUTH.format(job_id=_SCENE_JOB)
    revision = world.registry.scene.current(_SCENE_JOB).scene.scene_revision
    skewed = {"scene_revision": revision, "tagged_at": "2001-01-01T00:00:00+00:00"}

    first = await client.put(url, json=_truth_body(0, layouts={"A": skewed}))
    tagged = first.json()["truth"]["layouts"]["A"]["tagged_at"]
    second = await client.put(url, json=_truth_body(1, layouts={"A": skewed}, notes="sửa ghi chú"))

    assert first.status_code == 200 and not tagged.startswith("2001")
    assert second.status_code == 200 and second.json()["truth"]["layouts"]["A"]["tagged_at"] == tagged


@pytest.mark.asyncio
async def test_layouts_a_and_b_must_be_different_revisions(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(None)
    revision = world.registry.scene.current(_SCENE_JOB).scene.scene_revision
    layout = {"scene_revision": revision, "tagged_at": "2026-10-16T08:00:00+00:00"}

    response = await client.put(
        _TRUTH.format(job_id=_SCENE_JOB), json=_truth_body(0, layouts={"A": layout, "B": layout})
    )

    assert response.status_code == 422
    assert "khác nhau" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_stored_obstacle_that_left_the_scene_does_not_block_later_saves(
    client: AsyncClient, world: SimpleNamespace, as_user, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    """Chỉ id vật cản mới thêm được đối chiếu với scene; id đã lưu trước đó không chặn việc sửa phần khác."""
    from src.api.studio import value as value_routes
    from src.services.orchestration.value.ground_truth import BenchmarkTruth, write_truth

    as_user(None)
    database = value_routes._database()
    write_truth(database, _SCENE_JOB, 0, BenchmarkTruth(key_obstacle_ids=["vat-da-roi-scene"]))

    kept = await client.put(
        _TRUTH.format(job_id=_SCENE_JOB), json=_truth_body(1, key_obstacle_ids=["vat-da-roi-scene"])
    )
    added = await client.put(
        _TRUTH.format(job_id=_SCENE_JOB), json=_truth_body(2, key_obstacle_ids=["vat-da-roi-scene", "vat-moi-khong-co"])
    )

    assert kept.status_code == 200
    assert added.status_code == 422 and "vat-moi-khong-co" in added.json()["detail"]
    assert "vat-da-roi-scene" not in added.json()["detail"]


_SCORE = "/api/v1/jobs/{job_id}/value-metrics"
_BENCH = "/api/v1/value-metrics/benchmark"


@pytest.mark.asyncio
async def test_scorecard_of_a_job_without_ground_truth_is_unavailable_not_zero(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(None)

    response = await client.get(_SCORE.format(job_id=_SCENE_JOB))

    assert response.status_code == 200
    body = response.json()
    assert body["p2"]["unavailable_reason"] == "chưa có ground truth"
    assert body["p3"]["unavailable_reason"] == "chưa có ground truth"
    assert body["manual_baseline_minutes"]["provenance"] == "unavailable"
    assert body["north_star"]["hands_on_minutes"]["provenance"] == "unavailable"
    assert body["north_star"]["cost_usd"]["provenance"] == "unavailable"


@pytest.mark.asyncio
async def test_scorecard_exports_reject_an_unknown_job_with_404(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(None)

    for suffix in ("", ".md", ".csv"):
        response = await client.get(_SCORE.format(job_id="job-missing") + suffix)
        assert response.status_code == 404, suffix


@pytest.mark.asyncio
async def test_markdown_and_csv_exports_have_the_expected_shape(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(None)

    markdown = await client.get(_SCORE.format(job_id=_SCENE_JOB) + ".md")
    csv_response = await client.get(_SCORE.format(job_id=_SCENE_JOB) + ".csv")

    assert markdown.status_code == 200 and markdown.headers["content-type"].startswith("text/markdown")
    assert "| Metric | Giá trị | Nguồn |" in markdown.text
    assert csv_response.status_code == 200 and csv_response.headers["content-type"].startswith("text/csv")
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    assert csv_response.content.decode("utf-8-sig").splitlines()[0].startswith("Scene,Nguồn,Phần cứng")


@pytest.mark.asyncio
async def test_benchmark_lists_only_jobs_marked_for_the_benchmark(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(None)
    write_truth(world.database, _SCENE_JOB, 0, BenchmarkTruth(include_in_benchmark=True, notes="benchmark"))

    response = await client.get(_BENCH)
    markdown = await client.get(_BENCH + ".md")
    csv_response = await client.get(_BENCH + ".csv")

    assert response.status_code == 200
    job_ids = [row["job_id"] for row in response.json()["rows"]]
    assert _SCENE_JOB in job_ids
    assert world.job_id not in job_ids
    assert response.json()["summary"]["scenes"] == len(job_ids)
    assert markdown.status_code == 200 and "Bộ benchmark giá trị" in markdown.text
    assert csv_response.status_code == 200 and csv_response.content.startswith(b"\xef\xbb\xbf")


@pytest.mark.asyncio
async def test_benchmark_takes_the_newest_marked_job_of_each_project(
    client: AsyncClient, world: SimpleNamespace, as_user
) -> None:  # noqa: ANN001
    as_user(None)
    newer = world.registry.create_job(
        JobCreateInput(project_id="project-fixture-001"),
        requested_by=Actor(user_id="user-owner", display_name="Owner", role="guest"),
        owner_user_id="user-owner",
    )
    write_truth(world.database, world.job_id, 0, BenchmarkTruth(include_in_benchmark=True))
    write_truth(world.database, newer.job_id, 0, BenchmarkTruth(include_in_benchmark=True))

    response = await client.get(_BENCH)

    job_ids = [row["job_id"] for row in response.json()["rows"]]
    assert newer.job_id in job_ids
    assert world.job_id not in job_ids
