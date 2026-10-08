"""Đăng nhập ba role, mã mời một lần, phiên cookie và nhật ký thao tác.

Mọi state nằm trong runtime DB; token phiên và mã mời chỉ lưu dạng băm SHA-256.
Kiểm quyền nằm ở backend (route dependency); UI chỉ ẩn nút.
"""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.services.orchestration.auth.models import (
    ROLE_RANK,
    Actor,
    AuditEntry,
    InviteRecord,
    InviteRole,
    PublicUser,
    Role,
    SessionRecord,
    UserRecord,
)
from src.services.orchestration.auth.passwords import hash_password, token_digest, verify_password
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction


class AuthError(PermissionError):
    """Sai thông tin đăng nhập hoặc mã mời; message hiển thị được, không lộ chi tiết."""


#: Hash giả để thời gian đăng nhập sai email ≈ sai mật khẩu (tránh dò email).
_DUMMY_HASH = hash_password("dummy-password-for-timing")
_USER_EMAIL_LOCK_NAMESPACE = 0x523253  # "R2S" namespace for PostgreSQL registration locks.


def public(user: UserRecord) -> PublicUser:
    """Bỏ hash trước khi trả cho client."""
    return PublicUser(**user.model_dump(exclude={"password_hash", "created_at"}))


def has_role(user: UserRecord, required: Role) -> bool:
    """Reviewer có mọi quyền của Editor."""
    return user.active and ROLE_RANK[user.role] >= ROLE_RANK[required]


def has_unlimited_quota(user: UserRecord) -> bool:
    """Reviewer không bị giới hạn số scene/ngày; hạn mức chỉ áp cho Editor."""
    return user.role == "reviewer"


class AuthService:
    """Mỗi request một instance; không giữ state ngoài DB."""

    def __init__(self, database: RuntimeDatabase, session_days: int = 7, invite_days: int = 7) -> None:
        self.database = database
        self.session_ttl = timedelta(days=session_days)
        self.invite_ttl = timedelta(days=invite_days)

    # --- tài khoản ---------------------------------------------------------

    @staticmethod
    def _new_user(email: str, display_name: str, password: str, role: Role) -> UserRecord:
        """Dựng record (kiểm email/mật khẩu) trước khi mở transaction."""
        return UserRecord(
            user_id=f"user-{uuid4().hex[:12]}",
            email=email,
            display_name=display_name.strip(),
            role=role,
            password_hash=hash_password(password),
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _insert_user(tx: RuntimeTransaction, user: UserRecord) -> None:
        # SQLite serializes writers at BEGIN IMMEDIATE. PostgreSQL locks this normalized
        # email so concurrent registrations return a domain conflict before INSERT.
        if tx.postgres:
            tx.execute(
                "SELECT pg_advisory_xact_lock(?, hashtext(?))",
                (_USER_EMAIL_LOCK_NAMESPACE, user.email),
            )
        if tx.execute("SELECT 1 FROM r2s_users WHERE email=?", (user.email,)).fetchone():
            raise RuntimeStateConflictError("Email đã có tài khoản")
        tx.execute(
            "INSERT INTO r2s_users(user_id, email, payload) VALUES (?, ?, ?)",
            (user.user_id, user.email, user.model_dump_json()),
        )

    def create_user(self, email: str, display_name: str, password: str, role: Role) -> UserRecord:
        """Tạo tài khoản; email trùng → RuntimeStateConflictError."""
        user = self._new_user(email, display_name, password, role)
        with self.database.transaction(write=True) as tx:
            self._insert_user(tx, user)
        self.audit(user.user_id, "user.create", user.user_id, {"role": role})
        return user

    def get_user(self, user_id: str) -> UserRecord | None:
        """Đọc tài khoản theo id."""
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_users WHERE user_id=?", (user_id,)).fetchone()
        return UserRecord.model_validate_json(row[0]) if row else None

    def actors(self) -> dict[str, Actor]:
        """Tên hiện tại cho ID legacy; không gán role hiện tại thành historical snapshot."""
        return {user.user_id: Actor(user_id=user.user_id, display_name=user.display_name) for user in self.list_users()}

    def list_users(self) -> list[UserRecord]:
        """Mọi tài khoản, cũ nhất trước."""
        with self.database.transaction() as tx:
            rows = tx.execute("SELECT payload FROM r2s_users").fetchall()
        return sorted((UserRecord.model_validate_json(row[0]) for row in rows), key=lambda user: user.created_at)

    def update_user(
        self,
        actor: UserRecord,
        user_id: str,
        *,
        role: Role | None = None,
        active: bool | None = None,
        daily_job_quota: int | None = None,
    ) -> UserRecord:
        """Reviewer đổi role/khóa/hạn mức; không tự hạ quyền hay tự khóa chính mình."""
        if not has_role(actor, "reviewer"):
            raise AuthError("Chỉ Reviewer được quản lý thành viên")
        if role is not None and role not in ROLE_RANK:
            raise ValueError("Role không hợp lệ")
        if user_id == actor.user_id and (
            (role is not None and ROLE_RANK[role] < ROLE_RANK[actor.role]) or active is False
        ):
            raise AuthError("Không tự hạ quyền hoặc tự khóa tài khoản của mình")
        with self.database.transaction(write=True) as tx:
            row = tx.execute("SELECT payload FROM r2s_users WHERE user_id=?" + tx.lock_suffix(), (user_id,)).fetchone()
            if row is None:
                raise LookupError("Không có tài khoản này")
            changes = {
                key: value
                for key, value in {"role": role, "active": active, "daily_job_quota": daily_job_quota}.items()
                if value is not None
            }
            previous = UserRecord.model_validate_json(row[0])
            updated = UserRecord.model_validate({**previous.model_dump(), **changes})
            tx.execute("UPDATE r2s_users SET payload=? WHERE user_id=?", (updated.model_dump_json(), user_id))
            if active is False:
                tx.execute("DELETE FROM r2s_sessions WHERE user_id=?", (user_id,))
        self.audit(actor.user_id, "user.update", user_id, {key: str(value) for key, value in changes.items()})
        return updated

    # --- phiên ---------------------------------------------------------------

    def login(self, email: str, password: str) -> tuple[str, UserRecord]:
        """Trả token phiên (đặt vào cookie) và tài khoản; sai → AuthError chung."""
        normalized = email.strip().lower()
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_users WHERE email=?", (normalized,)).fetchone()
        user = UserRecord.model_validate_json(row[0]) if row else None
        valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
        if user is None or not valid or not user.active:
            self.audit(None, "auth.login_failed", None, {})
            raise AuthError("Sai email hoặc mật khẩu")
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session = SessionRecord(
            token_hash=token_digest(token), user_id=user.user_id, created_at=now, expires_at=now + self.session_ttl
        )
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_sessions(token_hash, user_id, expires_at, payload) VALUES (?, ?, ?, ?)",
                (session.token_hash, user.user_id, session.expires_at.isoformat(), session.model_dump_json()),
            )
        self.audit(user.user_id, "auth.login", user.user_id, {})
        return token, user

    def session_user(self, token: str | None) -> UserRecord | None:
        """Tài khoản của phiên còn hạn; phiên hết hạn bị xóa."""
        if not token:
            return None
        digest = token_digest(token)
        with self.database.transaction() as tx:
            row = tx.execute("SELECT payload FROM r2s_sessions WHERE token_hash=?", (digest,)).fetchone()
        if row is None:
            return None
        session = SessionRecord.model_validate_json(row[0])
        if session.expires_at <= datetime.now(UTC):
            self.logout(token)
            return None
        user = self.get_user(session.user_id)
        return user if user is not None and user.active else None

    def logout(self, token: str | None) -> None:
        """Xóa phiên; gọi nhiều lần vẫn an toàn."""
        if token:
            with self.database.transaction(write=True) as tx:
                tx.execute("DELETE FROM r2s_sessions WHERE token_hash=?", (token_digest(token),))

    # --- mã mời ---------------------------------------------------------------

    def create_invite(self, actor: UserRecord, role: InviteRole) -> tuple[str, InviteRecord]:
        """Reviewer phát mã mời một lần; mã gốc chỉ trả về lần này."""
        if not has_role(actor, "reviewer"):
            raise AuthError("Chỉ Reviewer được mời thành viên")
        code = secrets.token_urlsafe(12)
        now = datetime.now(UTC)
        invite = InviteRecord(
            code_hash=token_digest(code),
            role=role,
            created_by=actor.user_id,
            created_at=now,
            expires_at=now + self.invite_ttl,
        )
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_invites(code_hash, payload) VALUES (?, ?)",
                (invite.code_hash, invite.model_dump_json()),
            )
        self.audit(actor.user_id, "invite.create", None, {"role": role})
        return code, invite

    def register_guest(self, email: str, display_name: str, password: str) -> UserRecord:
        """Tạo tài khoản Guest không cần invite; role do server gán và email chưa được xác minh."""
        user = self._new_user(email, display_name, password, "guest")
        with self.database.transaction(write=True) as tx:
            self._insert_user(tx, user)
        self.audit(user.user_id, "user.create", user.user_id, {"role": user.role, "via": "public_signup"})
        return user

    def register(self, code: str, email: str, display_name: str, password: str) -> UserRecord:
        """Dùng mã mời tạo tài khoản với đúng role của mã; mã chỉ dùng được một lần."""
        digest = token_digest(code.strip())
        # Kiểm email/mật khẩu trước; role thật lấy từ mã mời bên trong transaction.
        candidate = self._new_user(email, display_name, password, "editor")
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_invites WHERE code_hash=?" + tx.lock_suffix(), (digest,)
            ).fetchone()
            invite = InviteRecord.model_validate_json(row[0]) if row else None
            if invite is None or invite.used_by is not None or invite.expires_at <= datetime.now(UTC):
                raise AuthError("Mã mời không hợp lệ, đã dùng hoặc đã hết hạn")
            # Tạo tài khoản và đánh dấu mã đã dùng trong CÙNG transaction: lỗi giữa chừng
            # rollback cả hai, mã không bị kẹt và hai request không cùng dùng một mã.
            user = candidate.model_copy(update={"role": invite.role})
            self._insert_user(tx, user)
            used = invite.model_copy(update={"used_by": user.user_id})
            tx.execute("UPDATE r2s_invites SET payload=? WHERE code_hash=?", (used.model_dump_json(), digest))
        self.audit(user.user_id, "user.create", user.user_id, {"role": user.role, "via": "invite"})
        return user

    # --- nhật ký & hạn mức ------------------------------------------------------

    def audit(self, user_id: str | None, action: str, target: str | None, details: dict[str, str]) -> None:
        """Ghi một dòng nhật ký bất biến."""
        entry = AuditEntry(
            entry_id=uuid4().hex, at=datetime.now(UTC), user_id=user_id, action=action, target=target, details=details
        )
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_audit_log(entry_id, at, user_id, action, payload) VALUES (?, ?, ?, ?, ?)",
                (entry.entry_id, entry.at.isoformat(), user_id, action, entry.model_dump_json()),
            )

    def recent_audit(self, limit: int = 100) -> list[AuditEntry]:
        """Nhật ký mới nhất trước."""
        with self.database.transaction() as tx:
            rows = tx.execute("SELECT payload FROM r2s_audit_log ORDER BY at DESC LIMIT ?", (limit,)).fetchall()
        return [AuditEntry.model_validate_json(row[0]) for row in rows]

    def count_actions(self, user_id: str, action: str, since: datetime) -> int:
        """Số lần một tài khoản làm một hành động kể từ `since` (dùng cho hạn mức job/ngày)."""
        with self.database.transaction() as tx:
            row = tx.execute(
                "SELECT COUNT(*) FROM r2s_audit_log WHERE user_id=? AND action=? AND at>=?",
                (user_id, action, since.isoformat()),
            ).fetchone()
        return int(row[0]) if row else 0
