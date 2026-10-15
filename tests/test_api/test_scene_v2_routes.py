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
async def test_membership_correction_routes_fail_closed_for_legacy_scene(client) -> None:
    merge = await client.post(
        f"{_JOB}/scene/corrections/merge",
        json={
            "expected_scene_revision": "rev-001",
            "membership_checksum": "sha256:" + "a" * 64,
            "primary_object_id": _PALLET,
            "secondary_object_ids": ["object-second"],
        },
    )
    reassign = await client.post(
        f"{_JOB}/scene/corrections/reassign",
        json={
            "expected_scene_revision": "rev-001",
            "membership_checksum": "sha256:" + "a" * 64,
            "region": {"min_xyz_m": [0, 0, 0], "max_xyz_m": [1, 1, 1]},
            "source_object_id": None,
            "target_object_id": _PALLET,
        },
    )

    assert merge.status_code == 422
    assert "no persisted Gaussian membership" in merge.json()["detail"]
    assert reassign.status_code == 422
    assert "no persisted Gaussian membership" in reassign.json()["detail"]


@pytest.mark.asyncio
async def test_membership_correction_rejects_stale_revision_before_dispatch(client) -> None:
    response = await client.post(
        f"{_JOB}/scene/corrections/merge",
        json={
            "expected_scene_revision": "rev-stale",
            "membership_checksum": "sha256:" + "a" * 64,
            "primary_object_id": _PALLET,
            "secondary_object_ids": ["object-second"],
        },
    )

    assert response.status_code == 409
    assert "current SceneIR is rev-001" in response.json()["detail"]


@pytest.mark.asyncio
async def test_lidar_collision_selection_rejects_candidate_not_published_for_job(client, monkeypatch) -> None:
    from src.api.product import scene as scene_api

    def selection_must_not_run(*_args, **_kwargs):
        raise AssertionError("unlisted candidate must be rejected before domain selection")

    monkeypatch.setattr(scene_api, "select_lidar_collision_candidate", selection_must_not_run)
    response = await client.post(
        f"{_JOB}/scene/collision-source/lidar",
        json={
            "expected_scene_revision": "rev-001",
            "candidate_manifest_ref": {
                "artifact_type": "LidarCollisionCandidateManifest",
                "schema_version": "1.0",
                "artifact_uri": f"artifact://jobs/job-fixture-001/collider/lidar-candidates/{'a' * 64}/manifest.json",
                "artifact_checksum": "sha256:" + "a" * 64,
                "data_class": "derived",
                "producer_stage": "ST-COLLIDER",
                "job_id": "job-fixture-001",
            },
        },
    )

    assert response.status_code == 404
    assert "allow-list" in response.json()["detail"]


@pytest.mark.asyncio
async def test_merge_route_publishes_and_returns_canonical_scene_revision(
    client, isolated_registry, monkeypatch, tmp_path
) -> None:
    from src.api.product import scene as scene_api
    from src.config import Settings

    runtime_python = tmp_path / "runtime-python"
    runtime_python.touch()
    monkeypatch.setattr(
        scene_api.deps,
        "settings",
        lambda: Settings(
            openai_api_key="test-only", product_scene_runtime_python=runtime_python, product_worker_root=tmp_path
        ),
    )
    monkeypatch.setattr(scene_api, "validate_object_membership_command", lambda _scene, _command: object())
    calls: list[dict[str, object]] = []

    def publish_correction(editor, job_id, command, **kwargs):  # noqa: ANN001, ANN202
        calls.append(kwargs)
        current = editor.current(job_id).scene
        updated = current.model_copy(
            update={"provenance": {**current.provenance, "membership_correction_test": command.primary_object_id}},
            deep=True,
        )
        return editor.publish_next(job_id, command.expected_scene_revision, updated, "membership_correction_test")

    monkeypatch.setattr(scene_api, "merge_object_candidates", publish_correction)

    response = await client.post(
        f"{_JOB}/scene/corrections/merge",
        json={
            "expected_scene_revision": "rev-001",
            "membership_checksum": "sha256:" + "a" * 64,
            "primary_object_id": _PALLET,
            "secondary_object_ids": ["object-second"],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["scene_revision"] == "rev-002"
    assert response.json()["scene"]["provenance"]["membership_correction_test"] == _PALLET
    assert (await client.get(f"{_JOB}/scene")).json()["scene_revision"] == "rev-002"
    assert calls[0]["actor_id"] == "local"
    assert calls[0]["runtime_python"] == runtime_python.resolve()


@pytest.mark.asyncio
async def test_collider_route_publishes_box_dimensions_and_local_pose(client, isolated_registry) -> None:
    original = isolated_registry.scene.current("job-fixture-001").scene
    original_object = next(item for item in original.objects if item.id == _PALLET)
    response = await client.post(
        f"{_JOB}/scene/collider",
        json={
            "expected_scene_revision": "rev-001",
            "object_id": _PALLET,
            "dimensions_xyz_m": [1.4, 0.8, 0.6],
            "local_translation_xyz_m": [0.2, -0.1, 0.3],
            "local_rotation_quaternion_xyzw": [0.0, 0.0, 0.7071067811865475, 0.7071067811865475],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["previous_scene_revision"], body["scene_revision"]) == ("rev-001", "rev-002")
    edited = _object(body, _PALLET)
    assert edited["collider"]["dimensions_xyz_m"] == pytest.approx([1.4, 0.8, 0.6])
    assert edited["collider"]["local_transform"]["translation_xyz"] == pytest.approx([0.2, -0.1, 0.3])
    assert edited["collider"]["local_transform"]["rotation_quaternion_xyzw"] == pytest.approx(
        [0.0, 0.0, 0.7071067811865475, 0.7071067811865475]
    )
    assert edited["collider"]["provenance"]["manual_override"]["operation"] == "collider_edit"
    assert body["scene"]["provenance"]["last_scene_operation"] == "edit_collider"
    assert body["scene"]["provenance"]["invalidates_validation"] is True
    assert edited["transform"] == original_object.transform.model_dump(mode="json")
    assert edited["geometry_ref"] == original_object.geometry_ref.model_dump(mode="json")
    assert edited["primitive_dimensions_xyz_m"] == original_object.primitive_dimensions_xyz_m
    if original_object.physics is not None:
        assert edited["physics"] == original_object.physics.model_dump(mode="json")
    else:
        assert "physics" not in edited
    assert isolated_registry.scene.current("job-fixture-001").scene.scene_revision == "rev-002"
    assert isolated_registry.scene.revision("job-fixture-001", "rev-001").scene == original


@pytest.mark.asyncio
async def test_collider_route_rejects_stale_and_empty_commands(client, isolated_registry) -> None:
    stale = await client.post(
        f"{_JOB}/scene/collider",
        json={
            "expected_scene_revision": "rev-009",
            "object_id": _PALLET,
            "dimensions_xyz_m": [1.2, 1.0, 0.8],
        },
    )
    empty = await client.post(
        f"{_JOB}/scene/collider",
        json={"expected_scene_revision": "rev-001", "object_id": _PALLET},
    )

    assert stale.status_code == 409
    assert empty.status_code == 422
    assert isolated_registry.scene.current("job-fixture-001").scene.scene_revision == "rev-001"


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
    # Client dùng revision này làm `expected_scene_revision` mà không phải tải cả scene.
    assert state.json()["scene_revision"] == "rev-001"

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
        auth_required=True,
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

    settings = Settings(
        app_env="production",
        auth_required=True,
        artifact_root=tmp_path / "artifacts",
        product_asset_preview_dir=tmp_path,
    )
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


@pytest.mark.asyncio
async def test_visual_membership_preview_rejects_stale_and_legacy_without_mutation(client, isolated_registry):
    before = isolated_registry.scene.current("job-fixture-001").scene
    command = {
        "expected_scene_revision": "rev-stale",
        "membership_checksum": "sha256:" + "a" * 64,
        "source_visual_checksum": "sha256:" + "b" * 64,
        "source_gaussian_indices": [0, 2],
        "source_object_id": _PALLET,
        "target_object_id": None,
    }
    stale = await client.post(f"{_JOB}/scene/membership/preview", json=command)
    assert stale.status_code == 409
    command["expected_scene_revision"] = before.scene_revision
    legacy = await client.post(f"{_JOB}/scene/membership/preview", json=command)
    assert legacy.status_code == 422
    assert isolated_registry.scene.current("job-fixture-001").scene == before


@pytest.mark.asyncio
async def test_visual_membership_apply_enqueues_exact_command_and_returns_202(client, monkeypatch):
    from src.api.product import scene as scene_api
    from src.services.orchestration.scene.objectify_queue import ObjectifyState

    seen = []

    def request(registry, settings, job_id, revision, mode, *, correction, actor_id):
        seen.append((job_id, revision, mode, correction, actor_id))
        return ObjectifyState(status="queued", mode="membership", base_revision=revision, phase="queued")

    monkeypatch.setattr(scene_api.objectify_queue, "request", request)
    monkeypatch.setattr(scene_api, "record_gpu_run", lambda *a: None)
    command = {
        "expected_scene_revision": "rev-001",
        "membership_checksum": "sha256:" + "a" * 64,
        "source_visual_checksum": "sha256:" + "b" * 64,
        "source_gaussian_indices": [0, 2],
        "source_object_id": _PALLET,
        "target_object_id": None,
    }
    response = await client.post(f"{_JOB}/scene/membership/regenerate", json=command)
    assert response.status_code == 202
    assert response.json()["mode"] == "membership" and response.json()["phase"] == "queued"
    assert seen[0][:3] == ("job-fixture-001", "rev-001", "membership")
    assert seen[0][3].source_gaussian_indices == [0, 2]
    assert seen[0][4] == "local"


def _as_draft(registry, monkeypatch) -> None:
    """Chỉ đổi revision mà route đọc: job mẫu coi như đang chờ tách vật, không ghi artifact nào."""
    current = registry.scene.current("job-fixture-001")
    draft = current.scene.model_copy(
        update={"provenance": {**current.scene.provenance, "object_geometry": "awaiting_review"}}
    )
    monkeypatch.setattr(registry.scene, "current", lambda job_id: current.model_copy(update={"scene": draft}))


@pytest.mark.asyncio
async def test_draft_scene_rejects_move_and_collider_edits_without_publishing(
    client, isolated_registry, monkeypatch
) -> None:
    _as_draft(isolated_registry, monkeypatch)
    move = await client.post(
        f"{_JOB}/scene/edits",
        json={
            "expected_scene_revision": "rev-001",
            "edits": [{"object_id": _PALLET, "translation_xyz": [3.0, 2.0, 0.0]}],
        },
    )
    collider = await client.post(
        f"{_JOB}/scene/collider",
        json={"expected_scene_revision": "rev-001", "object_id": _PALLET, "dimensions_xyz_m": [1.4, 0.8, 0.6]},
    )

    assert move.status_code == 422
    assert move.json()["detail"] == "Cần tạo mesh trước khi di chuyển/xoay vật."
    assert collider.status_code == 422
    assert collider.json()["detail"] == "Cần tạo mesh trước khi sửa collider."
    assert isolated_registry.scene.revision("job-fixture-001", "rev-002") is None


@pytest.mark.asyncio
async def test_draft_scene_refuses_walk_collision_for_the_current_and_a_pinned_revision(
    client, isolated_registry, monkeypatch
) -> None:
    _as_draft(isolated_registry, monkeypatch)
    params = {
        "artifact_uri": "artifact://jobs/job-fixture-001/rec05/abc/collision.glb",
        "artifact_checksum": "sha256:" + "1" * 64,
    }
    current = await client.get(f"{_JOB}/walk-collision/collision.glb", params=params)
    pinned = await client.get(f"{_JOB}/walk-collision/collision.glb", params={**params, "scene_revision": "rev-001"})

    assert current.status_code == 409
    assert current.json()["detail"] == "Cần tạo mesh trước khi Walk."
    assert pinned.status_code == 409
    assert pinned.json()["detail"] == "Cần tạo mesh trước khi Walk."


@pytest.mark.asyncio
async def test_draft_scene_refuses_simulation_package_without_publishing(
    client, isolated_registry, monkeypatch
) -> None:
    from src.api.studio import deps as studio_deps

    monkeypatch.setattr(studio_deps, "get_project_registry", lambda: isolated_registry)
    _as_draft(isolated_registry, monkeypatch)
    response = await client.post(f"{_JOB}/simulation-package")

    assert response.status_code == 409
    assert response.json()["detail"] == "Cần tạo mesh trước khi xuất USD."
    assert isolated_registry.scene.revision("job-fixture-001", "rev-002") is None


@pytest.mark.asyncio
async def test_draft_scene_refuses_adding_a_box_after_the_ready_path_passes(
    client, isolated_registry, monkeypatch
) -> None:
    payload = {"name": "Thùng", "dimensions_xyz_m": [0.6, 0.4, 0.5], "position_xyz": [1.0, 2.0, 0.25]}
    added = await client.post(f"{_JOB}/scene/objects", json={**payload, "expected_scene_revision": "rev-001"})
    assert added.status_code == 201
    _as_draft(isolated_registry, monkeypatch)

    refused = await client.post(f"{_JOB}/scene/objects", json={**payload, "expected_scene_revision": "rev-002"})

    assert refused.status_code == 422
    assert refused.json()["detail"] == "Cần tạo mesh trước khi thêm vật."
    assert isolated_registry.scene.revision("job-fixture-001", "rev-003") is None


@pytest.mark.asyncio
async def test_draft_scene_refuses_adding_a_catalog_asset(client, isolated_registry, monkeypatch) -> None:
    body = {"family": "SM_CardBoxA", "position_xyz": [2.0, 3.0, 0.0]}
    added = await client.post(f"{_JOB}/scene/catalog-objects", json={**body, "expected_scene_revision": "rev-001"})
    assert added.status_code == 201
    _as_draft(isolated_registry, monkeypatch)

    refused = await client.post(f"{_JOB}/scene/catalog-objects", json={**body, "expected_scene_revision": "rev-002"})

    assert refused.status_code == 422
    assert refused.json()["detail"] == "Cần tạo mesh trước khi thêm vật từ thư viện."
    assert isolated_registry.scene.revision("job-fixture-001", "rev-003") is None


@pytest.mark.asyncio
async def test_draft_scene_refuses_duplicating_an_object(client, isolated_registry, monkeypatch) -> None:
    duplicated = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/duplicate", json={"expected_scene_revision": "rev-001"}
    )
    assert duplicated.status_code == 201
    _as_draft(isolated_registry, monkeypatch)

    refused = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/duplicate", json={"expected_scene_revision": "rev-002"}
    )

    assert refused.status_code == 422
    assert refused.json()["detail"] == "Cần tạo mesh trước khi nhân bản vật."
    assert isolated_registry.scene.revision("job-fixture-001", "rev-003") is None


@pytest.mark.asyncio
async def test_draft_scene_refuses_collision_surface_marks(client, isolated_registry, monkeypatch) -> None:
    checksum = isolated_registry.scene.current("job-fixture-001").scene.environment.geometry_ref.artifact_checksum
    body = {"source_checksum": checksum, "kind": "floor", "points": [[0, 0, 0], [1, 0, 0], [0, 1, 0]]}
    marked = await client.post(f"{_JOB}/scene/collision-surfaces", json={**body, "expected_scene_revision": "rev-001"})
    assert marked.status_code == 201
    _as_draft(isolated_registry, monkeypatch)

    refused = await client.post(f"{_JOB}/scene/collision-surfaces", json={**body, "expected_scene_revision": "rev-002"})

    assert refused.status_code == 422
    assert refused.json()["detail"] == "Cần tạo mesh trước khi sửa bề mặt va chạm."
    assert isolated_registry.scene.revision("job-fixture-001", "rev-003") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["queued", "ready", "stale", "busy", "anonymous"])
async def test_geometry_build_route_returns_typed_queue_status(
    client, isolated_registry, tmp_path, monkeypatch, case
) -> None:
    from src.api import auth
    from src.api.product import deps as product_deps
    from src.api.product import scene as scene_api
    from src.config import Settings
    from src.models.contracts.reconstruction import ReconstructionBundle
    from tests.test_orchestration.test_scene_extraction import _FIXTURE

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'geometry-queue.db'}", product_objectify_remote_worker=True
    )
    monkeypatch.setattr(product_deps, "get_settings", lambda: settings)
    monkeypatch.setattr(scene_api, "record_gpu_run", lambda *args: None)
    bundle = ReconstructionBundle.model_validate_json(_FIXTURE.read_bytes())
    monkeypatch.setattr(scene_api.objectify_queue, "job_bundle", lambda *args: bundle)
    if case != "ready":
        _as_draft(isolated_registry, monkeypatch)
    if case == "busy":
        scene_api.objectify_queue.request(isolated_registry, settings, "job-fixture-001", "rev-001", "boxes")
    if case == "anonymous":
        monkeypatch.setattr(auth, "settings", lambda: settings.model_copy(update={"auth_required": True}))
        monkeypatch.setattr(auth, "current_user", lambda request: None)
    response = await client.post(
        f"{_JOB}/scene/geometry/build", json={"expected_scene_revision": "rev-009" if case == "stale" else "rev-001"}
    )
    assert response.status_code == {"queued": 202, "ready": 422, "stale": 409, "busy": 409, "anonymous": 401}[case]
    body = response.json()
    if case == "queued":
        assert body["status"] == "queued" and body["mode"] == "geometry"
        assert body["operation_id"] and body["base_revision"] == "rev-001" and body["phase"] is None
    else:
        assert set(body) == {"detail"}
        if case == "ready":
            assert body["detail"] == "Scene đã có hình học; dùng chỉnh vùng để dựng lại vật."


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["preview", "apply"])
@pytest.mark.parametrize("case", ["success", "stale", "checksum", "invalid", "ready"])
async def test_region_routes(client, tmp_path, monkeypatch, operation, case):
    from src.api.product import scene as scene_api
    from tests.test_scene.test_object_region import JOB, TARGET
    from tests.test_scene.test_object_region import draft as draft_fixture

    registry, scene, command, *_ = draft_fixture.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setattr(scene_api.deps, "registry", lambda: registry)
    monkeypatch.setattr(scene_api.deps, "job_or_404", lambda _: None)
    authorized = []
    monkeypatch.setattr(
        scene_api, "authorize_job_mutation", lambda user, reg, job_id, **kwargs: authorized.append((reg, job_id))
    )
    body = command.model_dump(mode="json")
    if case == "stale":
        body["expected_scene_revision"] = "rev-999"
    elif case == "checksum":
        body["membership_checksum"] = "sha256:" + "a" * 64
    elif case == "invalid":
        body["boxes"] = []
    elif case == "ready":
        current = registry.scene.publish_next(
            JOB,
            scene.scene_revision,
            scene.model_copy(update={"provenance": {"object_geometry": "ready"}}),
            "ready-fixture",
        ).revision.scene
        body["expected_scene_revision"] = current.scene_revision
    queued = []

    def fake_request(reg, settings, job_id, revision, mode, **kwargs):
        queued.append((job_id, revision, mode, kwargs["region"][0], kwargs["region"][1].model_dump(mode="json")))
        return scene_api.ObjectifyState(status="queued", mode=mode, base_revision=revision, operation_id="op-1")

    monkeypatch.setattr(scene_api.objectify_queue, "request", fake_request)
    response = await client.post(f"{_JOB}/scene/objects/{TARGET}/region/{operation}", json=body)
    expected = (
        409
        if case in {"stale", "checksum"}
        else 422
        if case == "invalid"
        else 202
        if case == "ready" and operation == "apply"
        else 200
        if operation == "preview"
        else 201
    )
    assert response.status_code == expected, response.text
    if case != "invalid":
        assert authorized == [(registry, JOB)]
    if expected == 201:
        assert response.json()["scene"]["scene_revision"] != scene.scene_revision
    elif expected == 200:
        assert response.json()["shell_glb_base64"]
    elif expected == 202:
        # A Ready scene queues a region rebuild of the affected objects instead of publishing directly.
        assert response.json()["mode"] == "region"
        assert queued == [(JOB, body["expected_scene_revision"], "region", TARGET, body)]
    elif case != "invalid":
        assert set(response.json()) == {"detail"}


@pytest.mark.asyncio
async def test_region_apply_on_ready_scene_without_membership_is_rejected(client):
    response = await client.post(
        f"{_JOB}/scene/objects/{_PALLET}/region/apply",
        json={
            "expected_scene_revision": "rev-001",
            "membership_checksum": "sha256:" + "a" * 64,
            "boxes": [{"op": "add", "center_m": [0, 0, 0], "half_extents_m": [0.3, 0.3, 0.3], "yaw_rad": 0}],
        },
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "scene has no persisted Gaussian membership"}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["queued", "busy", "stale", "checksum", "too_small"])
async def test_ready_region_apply_through_real_durable_queue(client, tmp_path, monkeypatch, isolated_registry, case):
    from pathlib import Path

    from src.api.product import scene as module
    from src.config import Settings
    from src.models.contracts.reconstruction import ReconstructionBundle
    from tests.test_scene.test_object_region import JOB, TARGET, draft

    registry, scene, command, *_ = draft.__wrapped__(tmp_path, monkeypatch)
    registry.get_job = isolated_registry.get_job
    scene = registry.scene.publish_next(
        JOB,
        scene.scene_revision,
        scene.model_copy(update={"provenance": {"object_geometry": "ready"}}),
        "ready-fixture",
    ).revision.scene
    command = command.model_copy(update={"expected_scene_revision": scene.scene_revision})
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'queue.db'}")
    bundle = ReconstructionBundle.model_validate_json(
        (Path(__file__).resolve().parents[2] / "fixtures/reconstruction_bundle/manifest.json").read_bytes()
    )
    monkeypatch.setattr(module.deps, "registry", lambda: registry)
    monkeypatch.setattr(module.deps, "settings", lambda: settings)
    monkeypatch.setattr(module.deps, "job_or_404", lambda _: None)
    monkeypatch.setattr(module, "authorize_job_mutation", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.objectify_queue, "job_bundle", lambda *args: bundle)
    body = command.model_dump(mode="json")
    if case == "busy":
        first = await client.post(f"{_JOB}/scene/objects/{TARGET}/region/apply", json=body)
        assert first.status_code == 202, first.text
    elif case == "stale":
        body["expected_scene_revision"] = "rev-999"
    elif case == "checksum":
        body["membership_checksum"] = "sha256:" + "a" * 64
    elif case == "too_small":
        body["boxes"][0]["half_extents_m"] = [0.005, 0.005, 0.005]
    result = await client.post(f"{_JOB}/scene/objects/{TARGET}/region/apply", json=body)
    assert result.status_code == (202 if case == "queued" else 422 if case == "too_small" else 409), result.text
    assert registry.scene.current(JOB).scene == scene
    if case == "queued":
        with module.objectify_queue._database(settings).transaction() as tx:
            record = module.objectify_queue._read(tx, JOB)
            assert record.region_command == command and record.region_object_id == TARGET
            assert record.actor_id == "local"
        assert result.json()["mode"] == "region" and result.json()["operation_id"]
    else:
        assert set(result.json()) == {"detail"}
