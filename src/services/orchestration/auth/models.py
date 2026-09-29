"""Tài khoản, mã mời, phiên đăng nhập và nhật ký thao tác (ADR 0003 §3, PRD §3.4)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

#: Chỉ hai role theo PRD §3.4; Reviewer có mọi quyền của Editor.
Role = Literal["editor", "reviewer"]
ROLE_RANK: dict[Role, int] = {"editor": 1, "reviewer": 2}


def _normalize_email(value: str) -> str:
    """Chuẩn hóa chữ thường; chỉ kiểm dạng cơ bản (tài khoản tạo qua mã mời, không gửi mail)."""
    cleaned = value.strip().lower()
    local, _, domain = cleaned.partition("@")
    if not local or "." not in domain or " " in cleaned or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Email không hợp lệ")
    return cleaned


Email = Annotated[str, Field(min_length=3, max_length=254), AfterValidator(_normalize_email)]


class UserRecord(BaseModel):
    """Một tài khoản; mật khẩu chỉ lưu dạng băm scrypt."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: Email
    display_name: str = Field(min_length=1, max_length=100)
    role: Role
    password_hash: str = Field(repr=False)
    active: bool = True
    created_at: datetime
    #: Hạn mức job mỗi ngày (giữ chi phí GPU).
    daily_job_quota: int = Field(default=10, ge=0, le=1000)


class PublicUser(BaseModel):
    """Thông tin trả cho client; không có hash."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: Email
    display_name: str
    role: Role
    active: bool
    daily_job_quota: int


class InviteRecord(BaseModel):
    """Mã mời một lần, gắn sẵn role; mã gốc chỉ hiện một lần lúc tạo."""

    model_config = ConfigDict(extra="forbid")

    code_hash: str
    role: Role
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
