"""Route sửa scene theo vật (pipeline v2): nhãn + vật lý, danh mục, thêm asset, nhân bản, xoá, hoàn tác."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_JOB = "/api/v1/jobs/job-fixture-001"
_PALLET = "object-pallet-001"


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from src.api.product import deps as product_deps
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    return registry


@pytest_asyncio.fixture
async def client():
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _object(body: dict, object_id: str) -> dict:
    return next(item for item in body["scene"]["objects"] if item["id"] == object_id)


@pytest.mark.asyncio
async def test_catalog_lists_classes_and_placeable_assets(client) -> None:
    body = (await client.get("/api/v1/scene/catalog")).json()

    assert "pallet" in body["classes"]
    pallet = next(entry for entry in body["entries"] if entry["family"] == "SM_PaletteA")
    assert pallet["dynamic"] is True and pallet["default_mass_kg"] == 25.0
    assert "tham khảo" in body["physics_note"]


@pytest.mark.asyncio
async def test_label_assigns_class_default_mass_then_user_mass(client) -> None:
    labelled = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/label", json={"expected_scene_revision": "rev-001", "semantic_class": "pallet"}
    )
    assert labelled.status_code == 201
    target = _object(labelled.json(), _PALLET)
    assert target["semantic_class"] == "pallet"
    assert (target["physics"]["mass_kg"], target["physics"]["mass_source"]) == (25.0, "catalog_default")

    custom = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/label",
        json={"expected_scene_revision": "rev-002", "semantic_class": "pallet", "mass_kg": 40.0},
    )
    physics = _object(custom.json(), _PALLET)["physics"]
    assert (physics["mass_kg"], physics["mass_source"]) == (40.0, "user")


@pytest.mark.asyncio
async def test_label_rejects_non_positive_mass(client) -> None:
    response = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/label",
        json={"expected_scene_revision": "rev-001", "semantic_class": "pallet", "mass_kg": 0},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_add_catalog_object_places_asset_on_floor_with_physics(client) -> None:
    response = await client.post(
        f"{_JOB}/scene/catalog-objects",
        json={"expected_scene_revision": "rev-001", "family": "SM_CardBoxA", "position_xyz": [2.0, 3.0, 0.0]},
    )
    assert response.status_code == 201
    added = _object(response.json(), "asset-001")

    assert added["origin"] == "user_added" and added["semantic_class"] == "box"
    assert added["primitive_dimensions_xyz_m"] == pytest.approx([0.7, 0.5, 0.5], abs=1e-3)
    assert added["transform"]["translation_xyz"] == pytest.approx([2.0, 3.0, 0.25], abs=1e-3)  # tâm = đáy + nửa cao
    assert added["physics"]["mass_source"] == "catalog_density"
    assert added["provenance"]["asset_url"].endswith("SM_CardBoxA_01.usd")


@pytest.mark.asyncio
async def test_add_unknown_or_structural_family_is_rejected(client) -> None:
    for family in ("khong-ton-tai", "SM_CeilingA_6X6"):
        response = await client.post(
            f"{_JOB}/scene/catalog-objects",
            json={"expected_scene_revision": "rev-001", "family": family, "position_xyz": [0, 0, 0]},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_delete_and_undo_round_trip(client) -> None:
    duplicated = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/duplicate", json={"expected_scene_revision": "rev-001"}
    )
    assert duplicated.status_code == 201 and duplicated.json()["scene_revision"] == "rev-002"
    assert _object(duplicated.json(), "user-001")["provenance"]["duplicated_from"] == _PALLET

    deleted = await client.post(f"{_JOB}/scene/objects/{_PALLET}/delete", json={"expected_scene_revision": "rev-002"})
    assert _object(deleted.json(), _PALLET)["provenance"]["review"] == "DELETED"

    # Hoàn tác về rev-001: revision mới (rev-004), nội dung vật như rev-001; lịch sử không bị xoá.
    undone = await client.post(
        f"{_JOB}/scene/restore", json={"expected_scene_revision": "rev-003", "target_revision": "rev-001"}
    )
    assert undone.status_code == 201 and undone.json()["scene_revision"] == "rev-004"
    ids = {item["id"] for item in undone.json()["scene"]["objects"]}
    assert "user-001" not in ids and _object(undone.json(), _PALLET)["active"] is True


@pytest.mark.asyncio
async def test_restore_with_stale_revision_conflicts_and_unknown_target_is_rejected(client) -> None:
    stale = await client.post(
        f"{_JOB}/scene/restore", json={"expected_scene_revision": "rev-009", "target_revision": "rev-001"}
    )
    assert stale.status_code == 409

    unknown = await client.post(
        f"{_JOB}/scene/restore", json={"expected_scene_revision": "rev-001", "target_revision": "rev-077"}
    )
    assert unknown.status_code == 422


@pytest.mark.asyncio
async def test_label_suggestions_use_object_size(client) -> None:
    response = await client.get(f"{_JOB}/scene/objects/{_PALLET}/label-suggestions")

    assert response.status_code == 200
    assert len(response.json()["suggestions"]) >= 1


@pytest.mark.asyncio
async def test_objectify_state_and_request_without_reconstruction_bundle(client, tmp_path, monkeypatch) -> None:
    from src.api.product import deps as product_deps
    from src.config import Settings

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'runtime.db'}")
    monkeypatch.setattr(product_deps, "get_settings", lambda: settings)

    state = await client.get(f"{_JOB}/scene/objectify")
    assert state.status_code == 200
    assert state.json()["status"] == "idle" and state.json()["object_centric"] is False

    # Job fixture không có ReconstructionBundle hệ mét → không xếp hàng, trả 409 có lý do.
    refused = await client.post(f"{_JOB}/scene/objectify", json={"expected_scene_revision": "rev-001", "mode": "boxes"})
    assert refused.status_code == 409 and "hệ mét" in refused.json()["detail"]
    stale = await client.post(f"{_JOB}/scene/objectify", json={"expected_scene_revision": "rev-009"})
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_cancel_objectify_returns_the_worker_cancellation_state(client, monkeypatch) -> None:
    from src.api.product import scene as scene_routes
    from src.services.orchestration.scene.objectify_queue import ObjectifyState

    state = ObjectifyState(status="running", mode="boxes", cancellation_requested=True)
    calls: list[tuple[str, str]] = []

    def cancel(registry, settings, job_id):  # noqa: ANN001, ANN202
        calls.append((job_id, settings.database_url))
        return state

    monkeypatch.setattr(scene_routes.objectify_queue, "cancel", cancel)
    response = await client.post(f"{_JOB}/scene/objectify/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["cancellation_requested"] is True
    assert calls and calls[0][0] == "job-fixture-001"


@pytest.mark.asyncio
async def test_label_remembers_chosen_asset_and_rejects_asset_of_other_class(client) -> None:
    labelled = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/label",
        json={"expected_scene_revision": "rev-001", "semantic_class": "pallet", "asset_family": "SM_PaletteA"},
    )
    assert labelled.status_code == 201
    assert _object(labelled.json(), _PALLET)["physics"]["provenance"]["asset_family"] == "SM_PaletteA"

    wrong = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/label",
        json={"expected_scene_revision": "rev-002", "semantic_class": "box", "asset_family": "SM_PaletteA"},
    )
    assert wrong.status_code == 422 and "không thuộc nhãn" in wrong.json()["detail"]


@pytest.mark.asyncio
async def test_catalog_preview_served_only_for_known_family_with_file(client, tmp_path, monkeypatch) -> None:
    from src.api.product import deps as product_deps
    from src.config import Settings

    (tmp_path / "SM_PaletteA.glb").write_bytes(b"glTF-fake")
    empty = tmp_path / "no-cc0"
    settings = Settings(product_asset_preview_dir=tmp_path, product_catalog_preview_dir=empty)
    monkeypatch.setattr(product_deps, "get_settings", lambda: settings)

    entries = (await client.get("/api/v1/scene/catalog")).json()["entries"]
    flags = {entry["family"]: entry["has_preview"] for entry in entries}
    assert flags["SM_PaletteA"] is True and flags["SM_CardBoxA"] is False

    served = await client.get("/api/v1/scene/catalog/SM_PaletteA/preview.glb")
    assert served.status_code == 200 and served.content == b"glTF-fake"
    assert (await client.get("/api/v1/scene/catalog/SM_CardBoxA/preview.glb")).status_code == 404
    assert (await client.get("/api/v1/scene/catalog/..%2F..%2Fsecret/preview.glb")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_env", "explicit", "served"),
    [("production", None, False), ("staging", None, False), ("production", True, True), ("development", False, False)],
)
async def test_isaac_previews_are_off_in_production_unless_enabled(
    client, tmp_path, monkeypatch, app_env, explicit, served
) -> None:
    from src.api.product import deps as product_deps
    from src.config import Settings

    (tmp_path / "SM_PaletteA.glb").write_bytes(b"glTF-fake")
    settings = Settings(
        app_env=app_env,
        artifact_root=tmp_path / "artifacts",
        product_asset_preview_dir=tmp_path,
        product_catalog_preview_dir=tmp_path / "no-cc0",
        product_isaac_asset_previews=explicit,
    )
    monkeypatch.setattr(product_deps, "get_settings", lambda: settings)

    entries = (await client.get("/api/v1/scene/catalog")).json()["entries"]
    assert next(item for item in entries if item["family"] == "SM_PaletteA")["has_preview"] is served
    response = await client.get("/api/v1/scene/catalog/SM_PaletteA/preview.glb")
    assert response.status_code == (200 if served else 404)


@pytest.mark.asyncio
async def test_training_recording_is_optional_and_served_only_for_known_job(client, tmp_path, monkeypatch) -> None:
    from src.api.product import deps as product_deps
    from src.config import Settings

    monkeypatch.setattr(product_deps, "get_settings", lambda: Settings(product_rerun_recording_dir=tmp_path))
    # Chưa có bản ghi: chế độ xem không khả dụng, pipeline không bị ảnh hưởng.
    assert (await client.get(f"{_JOB}/training-recording")).json() == {"available": False, "size_bytes": None}
    assert (await client.get(f"{_JOB}/training-recording.rrd")).status_code == 404

    job_id = _JOB.rsplit("/", 1)[-1]
    (tmp_path / f"{job_id}.rrd").write_bytes(b"RRF2-fake")
    assert (await client.get(f"{_JOB}/training-recording")).json() == {"available": True, "size_bytes": 9}
    served = await client.get(f"{_JOB}/training-recording.rrd")
    assert served.status_code == 200 and served.content == b"RRF2-fake"
    assert (await client.get("/api/v1/jobs/job-khong-co/training-recording.rrd")).status_code == 404


@pytest.mark.asyncio
async def test_dynamic_object_is_carved_at_its_original_place(client, isolated_registry) -> None:
    from src.services.orchestration.scene.physics import CARVE_MARGIN_M, dynamic_carve_boxes

    job = "job-fixture-001"
    original = next(item for item in isolated_registry.scene.current(job).scene.objects if item.id == _PALLET)
    # Vật tĩnh (chưa gán lớp có vật lý động) không bị khoét.
    assert dynamic_carve_boxes(isolated_registry, job, [_PALLET, "no-such-object"]) == []
    labelled = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/label", json={"expected_scene_revision": "rev-001", "semantic_class": "pallet"}
    )
    assert _object(labelled.json(), _PALLET)["physics"]["dynamic"] is True
    # Dời vật sang chỗ khác: vùng khoét vẫn là chỗ vật đứng lúc dựng lại scene (lưới tĩnh không đổi theo lần dời).
    scene = isolated_registry.scene.current(job).scene
    moved = scene.model_copy(
        update={
            "objects": [
                item.model_copy(
                    update={
                        "transform": item.transform.model_copy(update={"translation_xyz": (9.0, 9.0, 0.0)}),
                        "primitive_dimensions_xyz_m": (1.2, 0.8, 0.15),
                    }
                )
                if item.id == _PALLET
                else item
                for item in scene.objects
            ]
        }
    )
    isolated_registry.scene.publish_next(job, scene.scene_revision, moved, "test_move")
    [box] = dynamic_carve_boxes(isolated_registry, job, [_PALLET])
    assert box.rotation_xyzw == original.transform.rotation_quaternion_xyzw
    assert box.center != (9.0, 9.0, 0.0)
    assert box.half_extents == pytest.approx((0.6 + CARVE_MARGIN_M, 0.4 + CARVE_MARGIN_M, 0.075 + CARVE_MARGIN_M))


@pytest.mark.asyncio
async def test_cc0_previews_cover_every_placeable_family_even_in_production(client, tmp_path, monkeypatch) -> None:
    from src.api.product import deps as product_deps
    from src.config import Settings

    settings = Settings(app_env="production", artifact_root=tmp_path / "artifacts", product_asset_preview_dir=tmp_path)
    monkeypatch.setattr(product_deps, "get_settings", lambda: settings)

    entries = (await client.get("/api/v1/scene/catalog")).json()["entries"]
    assert entries and all(item["has_preview"] for item in entries)
    served = await client.get("/api/v1/scene/catalog/SM_PaletteA/preview.glb")
    assert served.status_code == 200 and served.content[:4] == b"glTF"


def test_cc0_previews_match_the_nvidia_asset_sizes() -> None:
    """Hình xem trước CC0 phải đúng kích thước asset NVIDIA mà gói Isaac sẽ dùng (cùng hộp collider trong SceneIR)."""
    import json
    from pathlib import Path

    from src.services.orchestration.jobs.display_glb import glb_bounds

    root = Path(__file__).resolve().parents[2] / "configs/product"
    catalog = {item["family"]: item for item in json.loads((root / "object_catalog_v1.json").read_text())["entries"]}
    index = json.loads((root / "catalog_previews/index.json").read_text())
    assert set(index) == {family for family, item in catalog.items() if item["placeable"]}
    for family in index:
        low, high = glb_bounds((root / "catalog_previews" / f"{family}.glb").read_bytes())
        assert (high - low) == pytest.approx(catalog[family]["size_xyz_m"], abs=2e-3), family
        assert (high + low) / 2 == pytest.approx([0, 0, 0], abs=2e-3), family
