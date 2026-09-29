"""Đăng nhập hai role, mã mời một lần, phiên, nhật ký (ADR 0003 §3) trên SQLite + PostgreSQL."""

from datetime import UTC, datetime, timedelta

import pytest

from src.services.orchestration.auth import AuthError, AuthService, has_role, public
from src.services.orchestration.auth.passwords import hash_password, token_digest, verify_password
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError

PASSWORD = "mat-khau-du-dai"


@pytest.fixture
def auth(runtime_database_url: str) -> AuthService:
    return AuthService(RuntimeDatabase(runtime_database_url))


def test_password_hash_roundtrip_and_rules() -> None:
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert verify_password(PASSWORD, stored)
    assert not verify_password("sai-mat-khau-123", stored)
    assert not verify_password(PASSWORD, "bcrypt$garbage")
    with pytest.raises(ValueError):
        hash_password("ngan")


def test_reviewer_invites_editor_who_logs_in(auth: AuthService) -> None:
    reviewer = auth.create_user("Lead@Example.com ", "Trưởng nhóm", PASSWORD, "reviewer")
    assert reviewer.email == "lead@example.com"
    code, invite = auth.create_invite(reviewer, "editor")
    assert invite.code_hash == token_digest(code) and code not in invite.model_dump_json()

    editor = auth.register(code, "dung@example.com", "Dựng scene", PASSWORD)
    assert editor.role == "editor"
    with pytest.raises(AuthError):
        auth.register(code, "khac@example.com", "Khác", PASSWORD)  # mã chỉ dùng một lần

    token, user = auth.login("DUNG@example.com", PASSWORD)
    assert user.user_id == editor.user_id
    assert auth.session_user(token).user_id == editor.user_id
    assert "password_hash" not in public(user).model_dump()
    auth.logout(token)
    assert auth.session_user(token) is None


def test_roles_are_hierarchical(auth: AuthService) -> None:
    editor = auth.create_user("e@example.com", "E", PASSWORD, "editor")
    reviewer = auth.create_user("r@example.com", "R", PASSWORD, "reviewer")
    assert has_role(reviewer, "editor") and has_role(reviewer, "reviewer")
    assert has_role(editor, "editor") and not has_role(editor, "reviewer")
    with pytest.raises(AuthError):
        auth.create_invite(editor, "editor")


def test_login_failures_are_uniform(auth: AuthService) -> None:
    auth.create_user("a@example.com", "A", PASSWORD, "editor")
    for email, password in [("a@example.com", "sai-mat-khau-00"), ("khong-co@example.com", PASSWORD)]:
        with pytest.raises(AuthError, match="Sai email hoặc mật khẩu"):
            auth.login(email, password)
    assert [entry.action for entry in auth.recent_audit()][:2] == ["auth.login_failed", "auth.login_failed"]


def test_duplicate_email_and_expired_invite(auth: AuthService) -> None:
    reviewer = auth.create_user("r@example.com", "R", PASSWORD, "reviewer")
    with pytest.raises(RuntimeStateConflictError):
        auth.create_user("R@example.com", "R2", PASSWORD, "editor")
    expired = AuthService(auth.database, invite_days=-1)
    code, _ = expired.create_invite(reviewer, "editor")
    with pytest.raises(AuthError):
        auth.register(code, "x@example.com", "X", PASSWORD)


def test_failed_registration_keeps_invite_usable(auth: AuthService) -> None:
    reviewer = auth.create_user("r@example.com", "R", PASSWORD, "reviewer")
    code, _ = auth.create_invite(reviewer, "reviewer")
    with pytest.raises(ValueError):
        auth.register(code, "x@example.com", "X", "ngan")  # mật khẩu quá ngắn
    assert auth.register(code, "x@example.com", "X", PASSWORD).role == "reviewer"


def test_deactivating_user_ends_sessions_and_self_lockout_is_refused(auth: AuthService) -> None:
    reviewer = auth.create_user("r@example.com", "R", PASSWORD, "reviewer")
    editor = auth.create_user("e@example.com", "E", PASSWORD, "editor")
    token, _ = auth.login("e@example.com", PASSWORD)
    auth.update_user(reviewer, editor.user_id, active=False)
    assert auth.session_user(token) is None
    with pytest.raises(AuthError):
        auth.login("e@example.com", PASSWORD)
    with pytest.raises(AuthError):
        auth.update_user(reviewer, reviewer.user_id, role="editor")


def test_expired_session_is_rejected(auth: AuthService) -> None:
    auth.create_user("e@example.com", "E", PASSWORD, "editor")
    short = AuthService(auth.database, session_days=-1)
    token, _ = short.login("e@example.com", PASSWORD)
    assert auth.session_user(token) is None


def test_count_actions_for_quota(auth: AuthService) -> None:
    editor = auth.create_user("e@example.com", "E", PASSWORD, "editor")
    for _ in range(3):
        auth.audit(editor.user_id, "scene.create", "project-x", {})
    since = datetime.now(UTC) - timedelta(days=1)
    assert auth.count_actions(editor.user_id, "scene.create", since) == 3
    assert auth.count_actions(editor.user_id, "scene.create", datetime.now(UTC) + timedelta(minutes=1)) == 0
