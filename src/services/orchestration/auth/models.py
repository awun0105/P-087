"""Tài khoản Guest/Editor/Reviewer, mã mời, phiên đăng nhập và nhật ký thao tác."""

import unicodedata
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

# Reviewer > Editor > Guest. Ownership remains a separate authorization check.
Role = Literal["guest", "editor", "reviewer"]
InviteRole = Literal["editor", "reviewer"]
ROLE_RANK: dict[Role, int] = {"guest": 1, "editor": 2, "reviewer": 3}


def _normalize_email(value: str) -> str:
    """Chuẩn hóa chữ thường; chỉ kiểm dạng cơ bản (tài khoản tạo qua mã mời, không gửi mail)."""
    cleaned = value.strip().lower()
    local, _, domain = cleaned.partition("@")
    if not local or "." not in domain or " " in cleaned or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Email không hợp lệ")
    return cleaned


Email = Annotated[str, Field(min_length=3, max_length=254), AfterValidator(_normalize_email)]


def _normalize_display_name(value: object) -> str:
    """Trim a Unicode display name and reject blank, multiline, or control text."""
    if not isinstance(value, str):
        raise ValueError("Tên hiển thị phải là chuỗi")
    if any(unicodedata.category(char) in {"Cc", "Zl", "Zp"} for char in value):
        raise ValueError("Tên hiển thị không được chứa ký tự điều khiển")
    return value.strip()


DisplayName = Annotated[str, BeforeValidator(_normalize_display_name), Field(min_length=1, max_length=100)]


class UserRecord(BaseModel):
    """Một tài khoản; mật khẩu chỉ lưu dạng băm scrypt."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: Email
    display_name: DisplayName
    role: Role
    password_hash: str = Field(repr=False)
    active: bool = True
    created_at: datetime
    #: Số lần xử lý GPU (scene mới hoặc thử lại) mỗi 24 giờ của Editor; Reviewer không giới hạn.
    daily_job_quota: int = Field(default=10, ge=0, le=1000)


class Actor(BaseModel):
    """Người thực hiện một thao tác (tải file, tạo scene, chạy job, duyệt), chụp lại lúc thao tác xảy ra.

    Studio là không gian chung của nhóm (ADR 0003): ai đăng nhập cũng thấy mọi scene, nên giao diện phải nói rõ thứ
    gì do ai làm. Tên được lưu kèm id để vẫn hiện được khi tài khoản đổi tên hoặc bị vô hiệu hoá.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    display_name: DisplayName
    #: Snapshot lúc thao tác. Bản ghi cũ không có thì để trống trong dữ liệu đã lưu; chỉ phản hồi API mới điền
    #: role hiện tại của đúng tài khoản đó (`with_current_role`), không bao giờ ghi ngược vào bản ghi.
    role: Role | None = Field(default=None, exclude_if=lambda value: value is None)


def actor_of(user: "UserRecord | None") -> Actor | None:
    """Actor của tài khoản đang đăng nhập; None khi deployment không bật đăng nhập (không biết ai thao tác)."""
    return None if user is None else Actor(user_id=user.user_id, display_name=user.display_name, role=user.role)


def with_current_role(actor: Actor | None, directory: dict[str, Actor]) -> Actor | None:
    """Actor kèm role hiện tại của tài khoản khi snapshot cũ không có role.

    Snapshot đã lưu luôn thắng. Tài khoản không còn trong `directory` thì giữ nguyên (role vẫn unknown).
    """
    if actor is None or actor.role is not None:
        return actor
    current = directory.get(actor.user_id)
    return actor if current is None or current.role is None else actor.model_copy(update={"role": current.role})


class PublicUser(BaseModel):
    """Thông tin trả cho client; không có hash."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: Email
    display_name: DisplayName
    role: Role
    active: bool
    daily_job_quota: int


class InviteRecord(BaseModel):
    """Mã mời một lần, gắn sẵn role; mã gốc chỉ hiện một lần lúc tạo."""

    model_config = ConfigDict(extra="forbid")

    code_hash: str
    role: InviteRole
    created_by: str
    created_at: datetime
    expires_at: datetime
    used_by: str | None = None


class SessionRecord(BaseModel):
    """Phiên đăng nhập; token gốc chỉ nằm trong cookie httpOnly."""

    model_config = ConfigDict(extra="forbid")

    token_hash: str
    user_id: str
    created_at: datetime
    expires_at: datetime


class AuditEntry(BaseModel):
    """Một dòng nhật ký: ai làm gì, trên đối tượng nào, lúc nào (PRD NFR-04)."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    at: datetime
    user_id: str | None
    action: str = Field(min_length=1, max_length=100)
    target: str | None = Field(default=None, max_length=200)
    details: dict[str, str] = Field(default_factory=dict)
