"""Explicit two-account seed rename migration."""

import pytest

from src.services.orchestration.auth import AuthService
from src.services.orchestration.auth.seed_migration import (
    SeedAccountMigrationError,
    migrate_seed_account_names,
)
from src.services.orchestration.jobs.database import RuntimeDatabase

PASSWORD = "mat-khau-du-dai"


@pytest.fixture
def auth(runtime_database_url: str) -> AuthService:
    return AuthService(RuntimeDatabase(runtime_database_url))


def test_seed_name_migration_is_idempotent_and_preserves_other_accounts_and_credentials(
    auth: AuthService,
) -> None:
    reviewer = auth.create_user("reviewer@example.com", "Reviewer cũ", PASSWORD, "reviewer")
    editor = auth.create_user("editor@example.com", "Editor cũ", PASSWORD, "editor")
    other = auth.create_user("other@example.com", "Tài khoản khác", PASSWORD, "reviewer")
    before = {user.user_id: user for user in (reviewer, editor, other)}

    assert migrate_seed_account_names(auth.database, reviewer.user_id, editor.user_id) == (
        reviewer.user_id,
        editor.user_id,
    )
    assert migrate_seed_account_names(auth.database, reviewer.user_id, editor.user_id) == ()

    updated_reviewer = auth.get_user(reviewer.user_id)
    updated_editor = auth.get_user(editor.user_id)
    untouched = auth.get_user(other.user_id)
    assert updated_reviewer is not None and updated_reviewer.display_name == "Minh An"
    assert updated_editor is not None and updated_editor.display_name == "Hà Linh"
    assert untouched == before[other.user_id]
    for updated, original in ((updated_reviewer, reviewer), (updated_editor, editor)):
        assert updated is not None
        assert updated.user_id == original.user_id
        assert updated.email == original.email
        assert updated.role == original.role
        assert updated.active == original.active
        assert updated.daily_job_quota == original.daily_job_quota
        assert updated.created_at == original.created_at
        assert updated.password_hash == original.password_hash


def test_seed_name_migration_rejects_wrong_or_missing_ids_atomically(auth: AuthService) -> None:
    reviewer = auth.create_user("reviewer@example.com", "Reviewer cũ", PASSWORD, "reviewer")
    another_reviewer = auth.create_user("other@example.com", "Reviewer khác", PASSWORD, "reviewer")

    with pytest.raises(SeedAccountMigrationError, match="role seed editor"):
        migrate_seed_account_names(auth.database, reviewer.user_id, another_reviewer.user_id)
    assert auth.get_user(reviewer.user_id).display_name == "Reviewer cũ"

    with pytest.raises(SeedAccountMigrationError, match="Không tìm thấy"):
        migrate_seed_account_names(auth.database, reviewer.user_id, "missing-editor-id")
    assert auth.get_user(reviewer.user_id).display_name == "Reviewer cũ"

    with pytest.raises(SeedAccountMigrationError, match="stable user ID riêng"):
        migrate_seed_account_names(auth.database, reviewer.user_id, reviewer.user_id)
