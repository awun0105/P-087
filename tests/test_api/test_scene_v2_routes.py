"""Route sửa scene theo vật (pipeline v2): nhãn + vật lý, danh mục, thêm asset, nhân bản, xoá, hoàn tác."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_JOB = "/api/v1/jobs/job-fixture-001"
_PALLET = "object-pallet-001"


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    from src.api import routes_product
    from src.services.orchestration.projects.registry import ProjectRegistry

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(routes_product, "get_project_registry", lambda: registry)
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
async def test_objectify_state_and_request_without_reconstruction_bundle(client) -> None:
    state = await client.get(f"{_JOB}/scene/objectify")
    assert state.status_code == 200
    assert state.json()["status"] == "idle" and state.json()["object_centric"] is False

    # Job fixture không có ReconstructionBundle hệ mét → không xếp hàng, trả 409 có lý do.
    refused = await client.post(f"{_JOB}/scene/objectify", json={"expected_scene_revision": "rev-001", "mode": "boxes"})
    assert refused.status_code == 409 and "hệ mét" in refused.json()["detail"]
    stale = await client.post(f"{_JOB}/scene/objectify", json={"expected_scene_revision": "rev-009"})
    assert stale.status_code == 409
