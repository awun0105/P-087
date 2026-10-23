"""Bản demo: đánh dấu mốc gốc, chỉnh scene rồi khôi phục — revision mới mang nội dung gốc, không chạy lại xử lý."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_JOB = "/api/v1/jobs/job-fixture-001"
_PALLET = "object-pallet-001"


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from src.api.product import deps as product_deps
    from src.api.studio import deps as studio_deps
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(studio_deps, "get_project_registry", lambda: registry)
    return registry


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_scene_is_not_a_demo_until_marked(client) -> None:
    state = (await client.get(f"{_JOB}/demo")).json()
    assert state["baseline"] is None and state["at_baseline"] is False
    reset = await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-001"})
    assert reset.status_code == 422 and "bản demo" in reset.json()["detail"]


@pytest.mark.asyncio
async def test_edit_then_reset_restores_the_marked_content_as_a_new_revision(client, isolated_registry) -> None:
    marked = (await client.post(f"{_JOB}/demo/baseline")).json()
    assert marked["baseline"]["scene_revision"] == "rev-001" and marked["at_baseline"] is True
    project = (await client.get("/api/v1/projects/project-fixture-001")).json()
    assert project["demo_baseline"]["job_id"] == "job-fixture-001"

    deleted = await client.post(f"{_JOB}/scene/objects/{_PALLET}/delete", json={"expected_scene_revision": "rev-001"})
    assert deleted.status_code == 201
    edited = (await client.get(f"{_JOB}/demo")).json()
    assert edited["current_revision"] == "rev-002" and edited["at_baseline"] is False

    reset = await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-002"})
    assert reset.status_code == 200
    body = reset.json()
    assert body["current_revision"] == "rev-003" and body["at_baseline"] is True
    scene = isolated_registry.scene.current("job-fixture-001").scene
    assert any(item.id == _PALLET for item in scene.objects)

    # Đang đúng mốc gốc thì khôi phục lần nữa không tạo revision thừa.
    again = (await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-003"})).json()
    assert again["current_revision"] == "rev-003"


@pytest.mark.asyncio
async def test_reset_with_a_stale_revision_conflicts(client) -> None:
    await client.post(f"{_JOB}/demo/baseline")
    await client.post(f"{_JOB}/scene/objects/{_PALLET}/delete", json={"expected_scene_revision": "rev-001"})
    stale = await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-001"})
    assert stale.status_code == 409 and "tải lại" in stale.json()["detail"]


@pytest.mark.asyncio
async def test_clearing_the_mark_keeps_the_scene(client) -> None:
    await client.post(f"{_JOB}/demo/baseline")
    await client.post(f"{_JOB}/scene/objects/{_PALLET}/delete", json={"expected_scene_revision": "rev-001"})
    cleared = (await client.delete(f"{_JOB}/demo/baseline")).json()
    assert cleared["baseline"] is None
    project = (await client.get("/api/v1/projects/project-fixture-001")).json()
    assert project["demo_baseline"] is None


def test_baseline_survives_a_database_backed_registry(tmp_path) -> None:
    from src.services.orchestration.jobs.database import RuntimeDatabase
    from src.services.orchestration.projects.registry import ProjectRegistry
    from src.services.orchestration.scene.demo import clear_demo, demo_state, mark_demo

    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database)
    registry.seed_from_fixtures()
    before = registry.get_project("project-fixture-001")
    # Mốc trống không được đổi bytes của bản ghi cũ (cập nhật project so khớp bytes).
    assert "demo_baseline" not in before.model_dump_json()

    mark_demo(registry, "job-fixture-001", None)
    reopened = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database)
    assert demo_state(reopened, "job-fixture-001").baseline.scene_revision == "rev-001"
    clear_demo(reopened, "job-fixture-001")
    assert reopened.get_project("project-fixture-001").demo_baseline is None


# --- Đặt làm bản demo = xuất vào thư viện mẫu -------------------------------------------------------------------


@pytest.fixture
def library(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.api.studio import deps as studio_deps

    root = tmp_path / "library"
    monkeypatch.setattr(
        studio_deps,
        "settings",
        lambda: SimpleNamespace(
            product_demo_dir=root,
            product_rerun_recording_dir=root / "recordings",
            database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
            artifact_s3_bucket=None,
            product_demo_object_prefix="demo/library",
        ),
    )
    return root


@pytest.fixture
def reviewer(monkeypatch):
    """Reviewer đã đăng nhập (xuất vào thư viện công khai luôn cần phiên thật) và nơi ghi nhật ký."""
    from types import SimpleNamespace

    from src.api import auth
    from src.main import app

    user = SimpleNamespace(user_id="user-reviewer", role="reviewer", display_name="Reviewer")
    audits: list[tuple] = []
    monkeypatch.setitem(app.dependency_overrides, auth.require_reviewer, lambda: user)
    monkeypatch.setattr(auth, "auth_service", lambda: SimpleNamespace(audit=lambda *args: audits.append(args)))
    return SimpleNamespace(user=user, audits=audits)


def _attest(registry, monkeypatch, **flags) -> None:
    project = registry.get_project(registry.get_job("job-fixture-001").project_id)
    patched = project.model_copy(update={"source_rights_attestation": {"attested": True, **flags}})
    monkeypatch.setattr(registry, "get_project", lambda project_id: patched)


_CONFIRMED = {"rights_to_use_confirmed": True, "anonymization_confirmed": True}


def _fake_publish(calls):
    from datetime import UTC, datetime

    from src.services.orchestration.samples import DemoFile, DemoManifest

    def fake(registry, job_id, root, *, catalog, title, description, source, frames=12, recording_dir=None):
        calls.append((job_id, root, title, description, source))
        (root / "kho-1").mkdir(parents=True)
        manifest = DemoManifest(
            demo_id="kho-1",
            title=title,
            description=description,
            origin="pipeline_job",
            source=source,
            produced_at=datetime(2026, 10, 10, tzinfo=UTC),
            provenance={"job_id": job_id},
            stages=[],
            splat=DemoFile(
                name="scene.sog", media_type="application/octet-stream", size_bytes=1, checksum="sha256:" + "0" * 64
            ),
        )
        (root / "kho-1" / "manifest.json").write_text(manifest.model_dump_json())
        return manifest

    return fake


class _InlineThread:
    """Chạy việc xuất "nền" ngay trong request để test đọc được kết quả."""

    def __init__(self, *, target, args=(), kwargs=None, **_ignored) -> None:
        self._run = lambda: target(*args, **(kwargs or {}))

    def start(self) -> None:
        self._run()


@pytest.fixture
def inline_publish(monkeypatch):
    from src.api.studio import demo as demo_api

    monkeypatch.setattr(demo_api, "Thread", _InlineThread)


def _patch_export(monkeypatch, fake) -> None:
    from src.services.orchestration.samples import export

    monkeypatch.setattr(export, "_publish_locked", fake)


@pytest.mark.asyncio
async def test_publish_needs_a_signed_in_reviewer_even_when_login_is_off(client, library) -> None:
    refused = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert refused.status_code == 401 and "Reviewer" in refused.json()["detail"]
    assert not library.exists()


@pytest.mark.asyncio
async def test_publish_needs_the_reviewer_to_confirm_public_release(client, library, reviewer) -> None:
    refused = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": False})
    assert refused.status_code == 422 and "công khai" in refused.json()["detail"]
    assert not library.exists()


@pytest.mark.asyncio
async def test_publish_refuses_scenes_without_rights_and_anonymization(
    client, library, reviewer, isolated_registry, monkeypatch
) -> None:
    refused = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert refused.status_code == 409 and "ẩn danh" in refused.json()["detail"]
    _attest(isolated_registry, monkeypatch, rights_to_use_confirmed=True, anonymization_confirmed=False)
    still = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert still.status_code == 409
    assert not library.exists()


@pytest.mark.asyncio
async def test_publish_exports_through_the_shared_service_and_audits_it(
    client, library, reviewer, isolated_registry, monkeypatch, inline_publish
) -> None:
    from src.services.orchestration.samples import DemoSource

    _attest(isolated_registry, monkeypatch, **_CONFIRMED)
    calls: list[tuple] = []
    _patch_export(monkeypatch, _fake_publish(calls))
    done = await client.post(
        f"{_JOB}/demo/publish", json={"confirm_public": True, "title": "Kho 1", "description": "Mô tả"}
    )
    assert done.status_code == 202 and done.json() == {"status": "publishing"}
    (job_id, root, title, description, source) = calls[0]
    assert (job_id, root, title, description) == ("job-fixture-001", library, "Kho 1", "Mô tả")
    assert isinstance(source, DemoSource) and source.dataset == "Real2Sim Studio"
    assert reviewer.audits == [("user-reviewer", "demo.publish", "job-fixture-001", {"sample_id": "kho-1"})]
    # Trạng thái demo của job báo mẫu đã có trong thư viện và không còn đang chuẩn bị.
    state = (await client.get(f"{_JOB}/demo")).json()
    assert (state["published_sample_id"], state["publishing"], state["publish_error"]) == ("kho-1", False, None)


@pytest.mark.asyncio
async def test_a_publish_in_progress_is_reported_and_blocks_a_second_one(
    client, library, reviewer, isolated_registry, monkeypatch
) -> None:
    from src.api.studio import demo as demo_api

    _attest(isolated_registry, monkeypatch, **_CONFIRMED)
    started: list[object] = []
    monkeypatch.setattr(demo_api, "Thread", lambda **kwargs: type("T", (), {"start": lambda self: started.append(1)})())
    done = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert done.status_code == 202 and started == [1]
    state = (await client.get(f"{_JOB}/demo")).json()
    assert state["publishing"] is True and state["published_sample_id"] is None
    again = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_a_blank_title_falls_back_to_the_scene_name_instead_of_failing(
    client, library, reviewer, isolated_registry, monkeypatch, inline_publish
) -> None:
    _attest(isolated_registry, monkeypatch, **_CONFIRMED)
    calls: list[tuple] = []
    _patch_export(monkeypatch, _fake_publish(calls))
    done = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True, "title": "    "})
    assert done.status_code == 202
    assert calls[0][2] == "Fixture warehouse project"


@pytest.mark.asyncio
async def test_publishing_a_job_twice_is_a_conflict_that_names_the_existing_sample(
    client, library, reviewer, isolated_registry, monkeypatch, inline_publish
) -> None:
    _attest(isolated_registry, monkeypatch, **_CONFIRMED)
    _patch_export(monkeypatch, _fake_publish([]))
    assert (await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})).status_code == 202
    reviewer.audits.clear()
    refused = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert refused.status_code == 409 and "kho-1" in refused.json()["detail"]
    assert reviewer.audits == []


@pytest.mark.asyncio
async def test_publish_reports_export_failures_on_the_demo_state(
    client, library, reviewer, isolated_registry, monkeypatch, inline_publish
) -> None:
    _attest(isolated_registry, monkeypatch, **_CONFIRMED)
    # Fixture không có preview đã xác minh: dịch vụ xuất từ chối thay vì tạo mẫu rỗng, và không để lại thư mục.
    accepted = await client.post(f"{_JOB}/demo/publish", json={"confirm_public": True})
    assert accepted.status_code == 202
    state = (await client.get(f"{_JOB}/demo")).json()
    assert state["publishing"] is False and "bản xem 3DGS" in state["publish_error"]
    assert [path for path in library.iterdir() if not path.name.startswith(".")] == []
    assert reviewer.audits == []
    missing = await client.post("/api/v1/jobs/job-nope/demo/publish", json={"confirm_public": True})
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_restore_root_and_reset_interaction(client, isolated_registry) -> None:
    original = isolated_registry.scene.current("job-fixture-001")
    original_path = isolated_registry.runtime_resolver.require(original.scene_reference)
    original_bytes = original_path.read_bytes()
    # 1. Ban đầu ở rev-001: at_root là True, at_baseline là False vì chưa đặt mốc.
    initial = (await client.get(f"{_JOB}/demo")).json()
    assert initial["current_revision"] == "rev-001"
    assert initial["at_root"] is True
    assert initial["at_baseline"] is False

    # 2. Xoá pallet -> rev-002, rồi đặt mốc gốc tại rev-002.
    deleted = await client.post(f"{_JOB}/scene/objects/{_PALLET}/delete", json={"expected_scene_revision": "rev-001"})
    assert deleted.status_code == 201
    marked = (await client.post(f"{_JOB}/demo/baseline")).json()
    assert marked["baseline"]["scene_revision"] == "rev-002"
    assert marked["at_baseline"] is True
    assert marked["at_root"] is False

    # 3. Bấm "Về bản gốc" -> quay về rev-001 gốc (tạo rev-003 mang nội dung rev-001).
    restored_root = await client.post(f"{_JOB}/demo/restore-root", json={"expected_scene_revision": "rev-002"})
    assert restored_root.status_code == 200
    body_root = restored_root.json()
    assert body_root["current_revision"] == "rev-003"
    assert body_root["at_root"] is True
    assert body_root["at_baseline"] is False  # Mốc đã đặt ở rev-002, hiện đang ở bản gốc nên at_baseline=False!

    # Kiểm tra pallet đã active trở lại trong scene ở rev-003 (bản gốc)
    scene_v3 = isolated_registry.scene.current("job-fixture-001").scene
    pallet_v3 = next(item for item in scene_v3.objects if item.id == _PALLET)
    assert pallet_v3.active is True

    # Đang ở bản gốc mà bấm về bản gốc tiếp thì không tạo revision thừa.
    again_root = (await client.post(f"{_JOB}/demo/restore-root", json={"expected_scene_revision": "rev-003"})).json()
    assert again_root["current_revision"] == "rev-003"

    # 4. Khi đang ở bản gốc nhưng đã có mốc đã lưu: bấm "Khôi phục mốc" -> quay lại rev-002 (tạo rev-004).
    restored_baseline = await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-003"})
    assert restored_baseline.status_code == 200
    body_baseline = restored_baseline.json()
    assert body_baseline["current_revision"] == "rev-004"
    assert body_baseline["at_baseline"] is True
    assert body_baseline["at_root"] is False

    # Pallet đã inactive (review=DELETED) theo đúng mốc đã lưu ở rev-002
    scene_v4 = isolated_registry.scene.current("job-fixture-001").scene
    pallet_v4 = next(item for item in scene_v4.objects if item.id == _PALLET)
    assert pallet_v4.active is False and pallet_v4.provenance.get("review") == "DELETED"
    assert body_baseline["baseline"]["scene_revision"] == "rev-002"

    # Saving again replaces only the user snapshot; the original artifact stays byte-for-byte intact.
    replaced = (await client.post(f"{_JOB}/demo/baseline")).json()
    assert replaced["baseline"]["scene_revision"] == "rev-004"
    root_again = await client.post(f"{_JOB}/demo/restore-root", json={"expected_scene_revision": "rev-004"})
    assert root_again.status_code == 200
    assert root_again.json()["at_root"] is True
    assert root_again.json()["baseline"]["scene_revision"] == "rev-004"
    saved_again = await client.post(f"{_JOB}/demo/reset", json={"expected_scene_revision": "rev-005"})
    assert saved_again.status_code == 200 and saved_again.json()["at_baseline"] is True
    assert original_path.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_restore_root_rejects_stale_revision_even_when_already_original(client) -> None:
    response = await client.post(f"{_JOB}/demo/restore-root", json={"expected_scene_revision": "rev-099"})
    assert response.status_code == 409
    unchanged = (await client.get(f"{_JOB}/demo")).json()
    assert unchanged["current_revision"] == "rev-001" and unchanged["at_root"] is True
