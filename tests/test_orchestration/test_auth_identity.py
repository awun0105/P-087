"""Stable account names and historical actor-role compatibility."""

import json

import pytest

from src.services.orchestration.auth import AuthService
from src.services.orchestration.auth.models import Actor, actor_of, with_current_role
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.uploads.scene_imports import ImportedScene

PASSWORD = "mat-khau-du-dai"


@pytest.fixture
def auth(runtime_database_url: str) -> AuthService:
    return AuthService(RuntimeDatabase(runtime_database_url))


def test_display_name_trims_unicode_and_rejects_blank_controls_and_overflow(auth: AuthService) -> None:
    user = auth.create_user("unicode@example.com", "  Hà Linh Nguyễn  ", PASSWORD, "editor")
    assert user.display_name == "Hà Linh Nguyễn"

    for index, name in enumerate(("", "   ", "bad\nname", "bad\x00name", "x" * 101)):
        with pytest.raises(ValueError):
            auth.create_user(f"invalid-{index}@example.com", name, PASSWORD, "editor")


def test_actor_role_is_snapshotted_and_legacy_actor_gets_the_current_role_only_in_responses(auth: AuthService) -> None:
    reviewer = auth.create_user("reviewer@example.com", "Minh An", PASSWORD, "reviewer")
    snapshot = actor_of(reviewer)
    assert snapshot is not None and snapshot.role == "reviewer"

    old_payload = '{"user_id":"legacy-user","display_name":"Tên cũ"}'
    legacy_actor = Actor.model_validate_json(old_payload)
    assert legacy_actor.role is None
    assert legacy_actor.model_dump_json() == old_payload
    # Bản ghi cũ vẫn không có role trong dữ liệu lưu; thư mục tài khoản cho role hiện tại để điền vào phản hồi.
    directory = auth.actors()
    assert directory[reviewer.user_id].role == "reviewer"
    filled = with_current_role(Actor(user_id=reviewer.user_id, display_name="Tên cũ"), directory)
    assert filled is not None and filled.role == "reviewer" and filled.display_name == "Tên cũ"
    assert legacy_actor.role is None
    # Snapshot đã lưu thắng; tài khoản không còn thì vẫn unknown.
    assert (
        with_current_role(Actor(user_id=reviewer.user_id, display_name="X", role="editor"), directory).role == "editor"
    )
    assert with_current_role(Actor(user_id="deleted-user", display_name="Y"), directory).role is None
    assert with_current_role(None, directory) is None


def test_legacy_import_payload_does_not_gain_a_historical_creator_role() -> None:
    payload = {
        "import_id": "import-legacy",
        "upload_id": "upload-legacy",
        "name": "Imported scene",
        "input_kind": "gaussian_ply",
        "status": "READY",
        "created_at": "2026-10-07T00:00:00Z",
        "created_by": "user-legacy",
        "created_by_name": "Tên cũ",
    }

    imported = ImportedScene.model_validate(payload)
    serialized = imported.model_dump(mode="json")
    assert imported.created_by_role is None
    assert "created_by_role" not in serialized
    assert serialized["created_by"] == "user-legacy"
    assert json.loads(imported.model_dump_json())["created_by_name"] == "Tên cũ"

    missing_creator = ImportedScene.model_validate(
        {
            "import_id": "import-unknown-creator",
            "upload_id": "upload-unknown-creator",
            "name": "Old scene",
            "input_kind": "gaussian_ply",
            "status": "READY",
            "created_at": "2026-10-07T00:00:00Z",
        }
    )
    assert missing_creator.created_by is None
    assert missing_creator.created_by_name is None
    assert missing_creator.created_by_role is None
