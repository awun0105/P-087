"""HTTP tests for the PRODUCT-06 scene endpoints.

Router note: the scene routes sit in the same product router as the project/job
routes, so the isolation fixture is duplicated here on purpose — each test module
must own its registry rather than share mutable state across files.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_JOB = "/api/v1/jobs/job-fixture-001"


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Per-test registry writing revisions into tmp_path, seeded from fixtures."""
    from src.api.product import deps as product_deps
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    return registry


@pytest_asyncio.fixture
async def client():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _scene(client) -> dict:
    response = await client.get(f"{_JOB}/scene")
    assert response.status_code == 200
    return response.json()


# ── reading the scene ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_scene_returns_revision(client) -> None:
    body = await _scene(client)
    assert body["job_id"] == "job-fixture-001"
    assert body["scene_revision"] == "rev-001"
    assert body["scene"]["scene_id"] == "scene-fixture-001"


@pytest.mark.asyncio
async def test_scene_response_carries_bindable_ref(client) -> None:
    body = await _scene(client)
    assert body["scene_uri"].startswith("artifact://jobs/job-fixture-001/scene/")
    assert body["scene_checksum"].startswith("sha256:")


@pytest.mark.asyncio
async def test_scene_response_has_no_filesystem_paths(client) -> None:
    r = await client.get(f"{_JOB}/scene")
    assert ":\\" not in r.text
    assert "artifact_root" not in r.text
    assert "fixtures/" not in r.text


@pytest.mark.asyncio
async def test_scene_reports_visual_is_not_brush_proof(client) -> None:
    """Fixture visual phải tự khai nó không phải bằng chứng Brush."""
    body = await _scene(client)
    # JSON fixture có metadata nhưng không phải payload Gaussian cho native loader.
    assert body["visual"]["available"] is False
    assert body["visual"]["unavailable_reason"]
    assert body["visual"]["brush_compatibility_proof"] is False


@pytest.mark.asyncio
async def test_scene_for_missing_job_404(client) -> None:
    r = await client.get("/api/v1/jobs/no-such-job/scene")
    assert r.status_code == 404


# ── editing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_bumps_revision_over_http(client) -> None:
    r = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["previous_scene_revision"] == "rev-001"
    assert body["scene_revision"] == "rev-002"


@pytest.mark.asyncio
async def test_edit_persists_so_next_read_sees_it(client) -> None:
    await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    body = await _scene(client)
    assert body["scene_revision"] == "rev-002"
    moved = next(item for item in body["scene"]["objects"] if item["id"] == "object-pallet-001")
    assert moved["transform"]["translation_xyz"] == [3.0, 2.0, 0.0]


@pytest.mark.asyncio
async def test_stale_edit_rejected_409(client) -> None:
    payload = {
        "expected_scene_revision": "rev-001",
        "edits": [{"object_id": "object-pallet-001", "translation_xyz": [1.0, 0.0, 0.0]}],
    }
    assert (await client.post(f"{_JOB}/scene/edits", json=payload)).status_code == 201
    assert (await client.post(f"{_JOB}/scene/edits", json=payload)).status_code == 409


@pytest.mark.asyncio
async def test_unknown_object_edit_rejected_422(client) -> None:
    r = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-khong-co", "translation_xyz": [1.0, 0.0, 0.0]}],
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unnormalized_quaternion_rejected(client) -> None:
    r = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "rotation_quaternion_xyzw": [0.0, 0.0, 0.5, 0.5]}],
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_edit_on_missing_job_404(client) -> None:
    r = await client.post(
        "/api/v1/jobs/no-such-job/scene/edits",
        json={"expected_scene_revision": "rev-001", "edits": [{"object_id": "x", "translation_xyz": [1, 0, 0]}]},
    )
    assert r.status_code == 404


# ── restart: revision state must outlive the process ─────────────────────────


def _restart_registry(tmp_path, monkeypatch):
    """Registry mới trên cùng runtime root — mô phỏng backend khởi động lại."""
    from src.api.product import deps as product_deps
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    return registry


@pytest.mark.asyncio
async def test_edit_after_restart_does_not_500(client, tmp_path, monkeypatch) -> None:
    """Regression: edit đầu tiên sau restart từng trả 500 thay vì revision mới."""
    first = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    assert first.status_code == 201
    assert first.json()["scene_revision"] == "rev-002"

    _restart_registry(tmp_path, monkeypatch)

    second = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-002",
            "edits": [{"object_id": "object-rack-001", "translation_xyz": [7.0, 7.0, 0.0]}],
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["scene_revision"] == "rev-003"


@pytest.mark.asyncio
async def test_scene_read_after_restart_reports_persisted_revision(client, tmp_path, monkeypatch) -> None:
    """Sau restart, `GET /scene` phải trả revision đã persist, không phải `rev-001`."""
    await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": "object-pallet-001", "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    _restart_registry(tmp_path, monkeypatch)
    assert (await _scene(client))["scene_revision"] == "rev-002"


# ── artifact content: allow-list, not free-form paths ────────────────────────


@pytest.mark.asyncio
async def test_geometry_bytes_are_served(client) -> None:
    body = await _scene(client)
    reference = body["scene"]["environment"]["geometry_ref"]
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={"artifact_uri": reference["artifact_uri"], "artifact_checksum": reference["artifact_checksum"]},
    )
    assert r.status_code == 200
    assert r.content.startswith(b"ply")


@pytest.mark.asyncio
async def test_evaluation_only_artifact_cannot_be_fetched(client) -> None:
    """`groundtruth_map.mock` nằm cùng thư mục job nhưng không được phép tải."""
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/evaluation_only/groundtruth_map.mock",
            "artifact_checksum": "sha256:" + "0" * 64,
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_artifact_from_another_job_cannot_be_fetched(client) -> None:
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={
            "artifact_uri": "artifact://jobs/job-khac-001/scene/object_pallet_geometry.ply",
            "artifact_checksum": "sha256:" + "0" * 64,
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_path_traversal_uri_is_rejected(client) -> None:
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/scene/../../mock_job/job_manifest.json",
            "artifact_checksum": "sha256:" + "0" * 64,
        },
    )
    assert r.status_code in {404, 422}


@pytest.mark.asyncio
async def test_wrong_checksum_is_rejected(client) -> None:
    """Allow-list rồi vẫn phải verify bytes: checksum sai thì fail closed."""
    body = await _scene(client)
    reference = body["scene"]["environment"]["geometry_ref"]
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={"artifact_uri": reference["artifact_uri"], "artifact_checksum": "sha256:" + "f" * 64},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_content_for_missing_job_404(client) -> None:
    r = await client.get(
        "/api/v1/jobs/no-such-job/artifacts/content",
        params={"artifact_uri": "artifact://jobs/x/y.ply", "artifact_checksum": "sha256:" + "0" * 64},
    )
    assert r.status_code == 404


# ── object actions / thêm vật cản (PRODUCT-07/07A) ───────────────────────────


@pytest.mark.asyncio
async def test_object_actions_publish_new_revisions(client) -> None:
    body = await _scene(client)
    object_id = body["scene"]["objects"][0]["id"]
    hidden = await client.post(
        f"{_JOB}/scene/objects/{object_id}/hide", json={"expected_scene_revision": "rev-001", "active": False}
    )
    assert hidden.status_code == 201, hidden.text
    assert hidden.json()["scene_revision"] == "rev-002"
    target = next(o for o in hidden.json()["scene"]["objects"] if o["id"] == object_id)
    assert target["active"] is False
    confirmed = await client.post(
        f"{_JOB}/scene/objects/{object_id}/confirm", json={"expected_scene_revision": "rev-002"}
    )
    assert confirmed.status_code == 201
    target = next(o for o in confirmed.json()["scene"]["objects"] if o["id"] == object_id)
    assert target["state"] == "CONFIRMED" and target["active"] is True
    # Vật đã xác nhận không "loại ứng viên" được nữa.
    ignored = await client.post(f"{_JOB}/scene/objects/{object_id}/ignore", json={"expected_scene_revision": "rev-003"})
    assert ignored.status_code == 422


@pytest.mark.asyncio
async def test_object_action_rejects_stale_revision_unknown_object_and_action(client) -> None:
    body = await _scene(client)
    object_id = body["scene"]["objects"][0]["id"]
    stale = await client.post(f"{_JOB}/scene/objects/{object_id}/confirm", json={"expected_scene_revision": "rev-009"})
    assert stale.status_code == 409
    missing = await client.post(
        f"{_JOB}/scene/objects/object-nope/confirm", json={"expected_scene_revision": "rev-001"}
    )
    assert missing.status_code == 422
    bad = await client.post(f"{_JOB}/scene/objects/{object_id}/explode", json={"expected_scene_revision": "rev-001"})
    assert bad.status_code == 422
    assert (await _scene(client))["scene_revision"] == "rev-001"  # không lệnh nào tạo revision


@pytest.mark.asyncio
async def test_add_box_obstacle_is_confirmed_user_object(client) -> None:
    payload = {
        "expected_scene_revision": "rev-001",
        "name": "Thùng",
        "dimensions_xyz_m": [0.6, 0.4, 0.5],
        "position_xyz": [1.0, 2.0, 0.25],
    }
    added = await client.post(f"{_JOB}/scene/objects", json=payload)
    assert added.status_code == 201, added.text
    box = next(o for o in added.json()["scene"]["objects"] if o["id"] == "user-001")
    assert box["state"] == "CONFIRMED" and box["origin"] == "user_added"
    assert box["transform"]["translation_xyz"] == [1.0, 2.0, 0.25]
    assert box["primitive_dimensions_xyz_m"] == [0.6, 0.4, 0.5]
    flat = await client.post(
        f"{_JOB}/scene/objects", json={**payload, "expected_scene_revision": "rev-002", "dimensions_xyz_m": [0, 1, 1]}
    )
    assert flat.status_code == 422


# ── walk collision: lưới va chạm xoay sang không gian hiển thị cho chế độ đi bộ ───────────


@pytest.mark.asyncio
async def test_walk_collision_serves_display_space_glb(client, tmp_path, monkeypatch) -> None:
    from src.services.orchestration.projects.registry import ProjectRegistry
    from tests.test_orchestration.test_display_glb import build_glb, parse

    source = tmp_path / "collision.glb"
    source.write_bytes(build_glb())
    seen: list[str] = []

    def resolve(self: ProjectRegistry, job_id: str, reference: object) -> object:
        seen.append(reference.artifact_uri)  # allow-list vẫn do registry quyết định
        return source

    monkeypatch.setattr(ProjectRegistry, "resolve_artifact", resolve)
    params = {
        "artifact_uri": "artifact://jobs/job-fixture-001/rec05/abc/collision.glb",
        "artifact_checksum": "sha256:" + "1" * 64,
    }
    r = await client.get(f"{_JOB}/walk-collision/collision.glb", params=params)
    assert r.status_code == 200 and r.headers["content-type"] == "model/gltf-binary"
    assert parse(r.content)[1].tolist() == [[0, 0, 0], [1, 0, 0], [0, 0, -2], [0, 3, 0]]
    assert seen == [params["artifact_uri"]] and source.read_bytes() == build_glb()  # artifact gốc không đổi
    # Tên file phải khớp ref và phải là .glb (viewer chọn loader theo đuôi).
    assert (await client.get(f"{_JOB}/walk-collision/other.glb", params=params)).status_code == 404
    source.write_bytes(b"not a glb")
    r = await client.get(f"{_JOB}/walk-collision/collision.glb", params=params)
    assert r.status_code == 409 and "lưới va chạm" in r.json()["detail"]


@pytest.mark.asyncio
async def test_walk_collision_respects_the_job_allow_list(client) -> None:
    r = await client.get(
        f"{_JOB}/walk-collision/secret.glb",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/evaluation_only/secret.glb",
            "artifact_checksum": "sha256:" + "0" * 64,
        },
    )
    assert r.status_code == 404
    body = await _scene(client)
    reference = body["scene"]["environment"]["geometry_ref"]  # artifact thật của job nhưng không phải GLB
    name = reference["artifact_uri"].rsplit("/", 1)[-1]
    r = await client.get(f"{_JOB}/walk-collision/{name}", params=reference)
    assert r.status_code == 404


# ── scene có artifact nhưng chưa có head (scene cũ trước AUD-10) ───────────────

_HEADLESS_PATHS = ["scene", "scene/objectify", "simulation-package", "review-state"]


async def _make_headless(client, registry, tmp_path, monkeypatch) -> None:
    from src.api.studio import deps as studio_deps
    from src.services.orchestration.jobs.database import RuntimeDatabase
    from src.services.orchestration.scene.heads import SceneHeadRepository

    monkeypatch.setattr(studio_deps, "get_project_registry", lambda: registry)
    await _scene(client)  # publish rev-001 khi chưa có head repository, như một scene cũ
    registry.scene.head_repository = SceneHeadRepository(RuntimeDatabase(f"sqlite:///{tmp_path / 'heads.db'}"))


@pytest.mark.asyncio
# `scene/objectify` đọc thêm hàng đợi objectify (cần DB runtime) nên chỉ kiểm ở ca bị chặn bên dưới.
@pytest.mark.parametrize("path", [path for path in _HEADLESS_PATHS if path != "scene/objectify"])
async def test_legacy_scene_without_head_opens_on_first_request(
    client, isolated_registry, tmp_path, monkeypatch, path
) -> None:
    await _make_headless(client, isolated_registry, tmp_path, monkeypatch)

    response = await client.get(f"{_JOB}/{path}")

    # Scene cũ tự nhận head sau khi kiểm xong; không còn bắt người vận hành chạy script tay.
    assert response.status_code == 200, response.text
    head = isolated_registry.scene.head_repository.get("job-fixture-001")
    assert head is not None and head.scene_revision == "rev-001"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _HEADLESS_PATHS)
async def test_legacy_scene_with_invalid_artifacts_is_a_conflict_with_a_user_message(
    client, isolated_registry, tmp_path, monkeypatch, path
) -> None:
    await _make_headless(client, isolated_registry, tmp_path, monkeypatch)
    resolver = isolated_registry.runtime_resolver
    uri = resolver.list_uris("artifact://jobs/job-fixture-001/scene/")[0]
    artifact = resolver.resolve(uri)
    artifact.write_bytes(artifact.read_bytes().replace(b"scene-fixture-001", b"scene-fixture-999"))

    response = await client.get(f"{_JOB}/{path}")

    # Dữ liệu hỏng vẫn bị chặn: 409 kèm câu cho người dùng, không lộ chi tiết vận hành.
    assert response.status_code == 409
    assert response.json()["detail"] == "Dữ liệu scene này không qua được bước kiểm tra. Nhờ quản trị kiểm tra scene."
    assert "scene_head" not in response.text


@pytest.mark.asyncio
async def test_legacy_scene_with_invalid_artifacts_refuses_walk_with_the_same_user_message(
    client, isolated_registry, tmp_path, monkeypatch
) -> None:
    await _make_headless(client, isolated_registry, tmp_path, monkeypatch)
    resolver = isolated_registry.runtime_resolver
    uri = resolver.list_uris("artifact://jobs/job-fixture-001/scene/")[0]
    artifact = resolver.resolve(uri)
    artifact.write_bytes(artifact.read_bytes().replace(b"scene-fixture-001", b"scene-fixture-999"))

    response = await client.get(
        f"{_JOB}/walk-collision/collision.glb",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/rec05/abc/collision.glb",
            "artifact_checksum": "sha256:" + "1" * 64,
        },
    )

    # Chưa rõ scene đang chờ duyệt hay không thì không cho Walk: cùng câu cho người dùng như các route scene khác.
    assert response.status_code == 409
    assert response.json()["detail"] == "Dữ liệu scene này không qua được bước kiểm tra. Nhờ quản trị kiểm tra scene."


@pytest.mark.asyncio
async def test_collision_surface_mark_fill_remove_and_stale_revision(client) -> None:
    current = await _scene(client)
    checksum = current["scene"]["environment"]["geometry_ref"]["artifact_checksum"]
    body = {
        "expected_scene_revision": current["scene_revision"],
        "source_checksum": checksum,
        "kind": "floor",
        "points": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    }
    marked = await client.post(f"{_JOB}/scene/collision-surfaces", json=body)
    assert marked.status_code == 201, marked.text
    value = marked.json()
    plane = value["scene"]["provenance"]["collision_surface_planes"][0]
    assert plane["origin"] == "user_authored" and plane["frame"] == "world"
    stale = await client.post(f"{_JOB}/scene/collision-surfaces", json=body)
    assert stale.status_code == 409
    filled = await client.post(
        f"{_JOB}/scene/collision-surfaces",
        json={
            "expected_scene_revision": value["scene_revision"],
            "source_checksum": checksum,
            "action": "fill",
            "plane_id": plane["id"],
        },
    )
    assert filled.status_code == 201, filled.text
    value = filled.json()
    assert value["scene"]["provenance"]["collision_surface_planes"][0]["fill_regions"] is True
    removed = await client.post(
        f"{_JOB}/scene/collision-surfaces",
        json={
            "expected_scene_revision": value["scene_revision"],
            "source_checksum": checksum,
            "action": "remove",
            "plane_id": plane["id"],
        },
    )
    assert removed.status_code == 201, removed.text
    assert removed.json()["scene"]["provenance"]["collision_surface_planes"] == []


# ── T-051: checksum-addressed artifacts are cached by the browser ────────────


async def _geometry_params(client) -> dict:
    reference = (await _scene(client))["scene"]["environment"]["geometry_ref"]
    return {"artifact_uri": reference["artifact_uri"], "artifact_checksum": reference["artifact_checksum"]}


@pytest.mark.asyncio
async def test_artifact_content_is_immutable_and_has_etag(client) -> None:
    params = await _geometry_params(client)
    r = await client.get(f"{_JOB}/artifacts/content", params=params)
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"] and "private" in r.headers["cache-control"]
    assert r.headers["etag"] == '"' + params["artifact_checksum"].removeprefix("sha256:") + '"'


@pytest.mark.asyncio
async def test_matching_if_none_match_returns_304_without_reading_file(client, monkeypatch) -> None:
    from src.api.product import deps as product_deps

    params = await _geometry_params(client)
    registry = product_deps.registry()

    def never(*args: object) -> None:
        raise AssertionError("file must not be resolved for a 304")

    monkeypatch.setattr(registry, "resolve_artifact", never)
    etag = '"' + params["artifact_checksum"].removeprefix("sha256:") + '"'
    r = await client.get(f"{_JOB}/artifacts/content", params=params, headers={"If-None-Match": etag})
    assert r.status_code == 304


@pytest.mark.asyncio
async def test_if_none_match_still_checks_permission(client) -> None:
    checksum = "0" * 64
    r = await client.get(
        f"{_JOB}/artifacts/content",
        params={
            "artifact_uri": "artifact://jobs/job-fixture-001/evaluation_only/groundtruth_map.mock",
            "artifact_checksum": "sha256:" + checksum,
        },
        headers={"If-None-Match": f'"{checksum}"'},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_artifact_range_request_still_works(client) -> None:
    params = await _geometry_params(client)
    r = await client.get(f"{_JOB}/artifacts/content", params=params, headers={"Range": "bytes=0-2"})
    assert r.status_code == 206 and r.content == b"ply"


# ── T-052: walk collision is composed once per revision ──────────────────────


def _fake_composition(monkeypatch, tmp_path):  # noqa: ANN001, ANN202
    from types import SimpleNamespace

    from src.api.product import artifacts as artifacts_route
    from src.services.orchestration.projects.registry import ProjectRegistry

    params = {
        "artifact_uri": "artifact://jobs/job-fixture-001/rec05/abc/collision.glb",
        "artifact_checksum": "sha256:" + "1" * 64,
    }
    source = tmp_path / "collision.glb"
    source.write_bytes(b"glb")
    monkeypatch.setattr(ProjectRegistry, "resolve_artifact", lambda self, job_id, reference: source)
    calls: list[str] = []

    def compose(registry, job_id, revision, *, preview_pending=False):  # noqa: ANN001, ANN202
        calls.append(revision)
        ref = SimpleNamespace(**params)
        scene = SimpleNamespace(environment=SimpleNamespace(collision_source_ref=None, geometry_ref=ref))
        background = SimpleNamespace(
            identity="identity-1", retained_shared_triangles=1, protected_surface_triangles=2, repaired_triangles=3
        )
        return scene, background

    monkeypatch.setattr(artifacts_route, "effective_collision_for_revision", compose)
    monkeypatch.setattr(artifacts_route, "effective_collision_bytes", lambda background, *, display: b"x" * 4096)
    return {**params, "scene_revision": "rev-001"}, calls


@pytest.mark.asyncio
async def test_walk_collision_second_request_skips_composition(client, monkeypatch, tmp_path) -> None:
    params, calls = _fake_composition(monkeypatch, tmp_path)
    first = await client.get(f"{_JOB}/walk-collision/collision.glb", params=params)
    second = await client.get(f"{_JOB}/walk-collision/collision.glb", params=params)
    assert first.status_code == second.status_code == 200
    assert second.content == first.content and len(calls) == 1
    assert "immutable" in first.headers["cache-control"]
    assert first.headers["x-collision-composition"] == "identity-1"


@pytest.mark.asyncio
async def test_walk_collision_if_none_match_returns_304(client, monkeypatch, tmp_path) -> None:
    params, calls = _fake_composition(monkeypatch, tmp_path)
    first = await client.get(f"{_JOB}/walk-collision/collision.glb", params=params)
    again = await client.get(
        f"{_JOB}/walk-collision/collision.glb", params=params, headers={"If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304 and len(calls) == 1


@pytest.mark.asyncio
async def test_walk_collision_stale_revision_still_409(client, monkeypatch, tmp_path) -> None:
    params, _ = _fake_composition(monkeypatch, tmp_path)
    await client.get(f"{_JOB}/walk-collision/collision.glb", params=params)
    stale = await client.get(f"{_JOB}/walk-collision/collision.glb", params={**params, "scene_revision": "rev-999"})
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_walk_collision_304_requires_permission(client, monkeypatch, tmp_path) -> None:
    params, _ = _fake_composition(monkeypatch, tmp_path)
    first = await client.get(f"{_JOB}/walk-collision/collision.glb", params=params)
    foreign = {**params, "artifact_uri": "artifact://jobs/job-fixture-001/evaluation_only/secret.glb"}
    r = await client.get(
        f"{_JOB}/walk-collision/secret.glb", params=foreign, headers={"If-None-Match": first.headers["etag"]}
    )
    assert r.status_code in {404, 409} and r.status_code != 304


# ── T-053: 304 for an unchanged scene, gzip for JSON, cached CORS preflight ──


@pytest.mark.asyncio
async def test_scene_etag_304(client) -> None:
    first = await client.get(f"{_JOB}/scene")
    assert first.status_code == 200 and first.headers["etag"]
    again = await client.get(f"{_JOB}/scene", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


@pytest.mark.asyncio
async def test_json_response_is_gzipped(client) -> None:
    r = await client.get(f"{_JOB}/scene", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


@pytest.mark.asyncio
async def test_binary_artifact_is_not_gzipped(client) -> None:
    params = await _geometry_params(client)
    r = await client.get(f"{_JOB}/artifacts/content", params=params, headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and "content-encoding" not in r.headers


@pytest.mark.asyncio
async def test_cors_preflight_has_max_age(client) -> None:
    from src.config import get_settings

    origin = get_settings().cors_origins[0]
    r = await client.options(
        f"{_JOB}/scene",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.headers.get("access-control-max-age") == "86400"
