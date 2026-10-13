"""Auth API: Guest signup, Editor/Reviewer invitation, phiên cookie và quản lý tài khoản.

Cookie đi qua proxy `/api/v1` của Web UI nên là cookie cùng domain với UI (không bị
chặn như cookie bên thứ ba). SameSite=Lax chặn request POST từ site khác mang cookie.
Khi `AUTH_REQUIRED=false` (local dev/test), các dependency quyền cho qua.
"""

import hashlib
import json
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import Settings, get_settings
from src.services.orchestration.auth import (
    AuditEntry,
    AuthError,
    AuthService,
    InviteRole,
    PublicUser,
    Role,
    UserRecord,
    has_role,
    public,
)
from src.services.orchestration.auth.quota import GuestQuotaExceededDetail, GuestQuotaSummary
from src.services.orchestration.auth.quota_ledger import (
    GuestQuotaExceededError,
    GuestQuotaIdempotencyConflictError,
    GuestQuotaIntent,
    QuotaOperation,
)
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError

SESSION_COOKIE = "r2s_session"
router = APIRouter(prefix="/auth", tags=["auth"])


def settings() -> Settings:
    """Settings hiện hành (patch được trong test)."""
    return get_settings()


def auth_service() -> AuthService:
    """Service đăng nhập trên runtime DB đang cấu hình."""
    current = settings()
    return AuthService(RuntimeDatabase(current.database_url), current.auth_session_days, current.auth_invite_days)


def current_user(request: Request) -> UserRecord | None:
    """Tài khoản của cookie phiên (None nếu chưa đăng nhập)."""
    return auth_service().session_user(request.cookies.get(SESSION_COOKIE))


def _require(role: Role):  # noqa: ANN202 - trả dependency FastAPI
    def dependency(request: Request) -> UserRecord | None:
        if not settings().auth_required:
            return None
        user = current_user(request)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cần đăng nhập")
        if not has_role(user, role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tài khoản không có quyền thao tác này")
        return user

    return dependency


#: Mô hình quyền: `require_contributor` = đã đăng nhập (Guest trở lên), `require_reviewer` = quản trị/duyệt.
#: Editor không có route riêng: khác Guest ở phạm vi sở hữu (xem `src/api/ownership.py`) và hạn mức, nên
#: resource mutation luôn cần thêm ownership guard bên cạnh dependency này.
require_contributor = _require("guest")
require_reviewer = _require("reviewer")

#: Hành động nhật ký cho mỗi lần xử lý GPU (scene mới hoặc thử lại) — đơn vị hạn mức.
GPU_RUN_ACTION = "gpu.run"


def enforce_gpu_quota(user: UserRecord | None) -> None:
    """Giữ rolling 24h quota hiện tại riêng cho Editor; Guest dùng calendar ledger."""
    if user is None or user.role != "editor":
        return
    since = datetime.now(UTC) - timedelta(days=1)
    if auth_service().count_actions(user.user_id, GPU_RUN_ACTION, since) >= user.daily_job_quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Đã dùng hết {user.daily_job_quota} lần xử lý GPU trong 24 giờ; nhờ Reviewer nâng hạn mức",
        )


def guest_run_intent(
    user: UserRecord | None,
    operation: QuotaOperation,
    idempotency_key: str | None,
    payload: dict[str, object],
) -> GuestQuotaIntent | None:
    """Build the server-owned Guest acceptance identity for a run-producing route."""
    if user is None or user.role != "guest":
        return None
    key = (idempotency_key or "").strip()
    if not key or len(key) > 200 or any(ord(char) < 0x21 or ord(char) > 0x7E for char in key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "idempotency_key_required", "message": "Guest run cần Idempotency-Key hợp lệ"},
        )
    fingerprint_payload = json.dumps(
        {"operation": operation, "payload": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return GuestQuotaIntent(
        actor_user_id=user.user_id,
        operation_kind=operation,
        idempotency_key=key,
        request_fingerprint=hashlib.sha256(fingerprint_payload).hexdigest(),
    )


def quota_exceeded_http(error: GuestQuotaExceededError) -> HTTPException:
    """Expose the stable quota code/summary instead of a message clients must parse."""
    detail = GuestQuotaExceededDetail(quota=error.summary)
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail.model_dump(mode="json"))


def idempotency_conflict_http(error: GuestQuotaIdempotencyConflictError) -> HTTPException:
    """Stable conflict for key reuse with a different request body."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "idempotency_key_conflict", "message": str(error)},
    )


def record_gpu_run(user: UserRecord | None, target: str, details: dict[str, str]) -> None:
    """Ghi một lần xử lý GPU vào nhật ký (dùng để tính hạn mức)."""
    if user is not None:
        auth_service().audit(user.user_id, GPU_RUN_ACTION, target, details)


class _LoginLimiter:
    """Giới hạn số lần đăng nhập theo IP trong một cửa sổ thời gian (mỗi process)."""

    def __init__(self, attempts: int = 10, window_seconds: float = 300) -> None:
        self.attempts = attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Thử đăng nhập quá nhiều lần; đợi vài phút"
                )
            hits.append(now)


#: Theo email: chống dò mật khẩu một tài khoản. Theo client: chống spam, ngưỡng rộng hơn
#: vì nhiều người có thể chung IP (proxy/NAT). Không khóa cả nhóm khi một người nhập sai.
login_limiter = _LoginLimiter(attempts=10, window_seconds=300)
client_limiter = _LoginLimiter(attempts=100, window_seconds=300)


def _client_key(request: Request) -> str:
    """IP client thật: phần tử đầu `X-Forwarded-For` (Vercel/Railway gắn), không thì IP kết nối.

    Header có thể bị giả; chỉ dùng cho giới hạn mềm theo client — giới hạn theo email mới
    là lớp bảo vệ tài khoản.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    return first or (request.client.host if request.client else "unknown")


class MeResponse(BaseModel):
    """Trạng thái đăng nhập cho UI."""

    model_config = ConfigDict(extra="forbid")

    auth_required: bool
    guest_signup_enabled: bool
    user: PublicUser | None
    quota: GuestQuotaSummary | None = None


class LoginRequest(BaseModel):
    """Email + mật khẩu."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    """Không có mã mời thì tạo Guest; mã hợp lệ cấp role của lời mời."""

    model_config = ConfigDict(extra="forbid")

    invite_code: str | None = Field(default=None, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("invite_code")
    @classmethod
    def _optional_invite(cls, value: str | None) -> str | None:
        code = value.strip() if value is not None else ""
        if code and len(code) < 4:
            raise ValueError("Mã mời phải có ít nhất 4 ký tự")
        return code or None


class GuestRegisterRequest(BaseModel):
    """Guest signup accepts identity fields only; role and invitation are server-controlled."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class InviteRequest(BaseModel):
    """Role gắn cho mã mời."""

    model_config = ConfigDict(extra="forbid")

    role: InviteRole


class InviteResponse(BaseModel):
    """Mã mời gốc — chỉ hiện một lần."""

    model_config = ConfigDict(extra="forbid")

    code: str
    role: InviteRole
    expires_at: str


class UserUpdate(BaseModel):
    """Reviewer đổi role/khóa/hạn mức."""

    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    active: bool | None = None
    daily_job_quota: int | None = Field(default=None, ge=0, le=1000)


def _set_session_cookie(response: Response, token: str) -> None:
    current = settings()
    secure = current.auth_cookie_secure
    if secure is None:
        secure = current.app_env not in {"development", "test"}
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=current.auth_session_days * 86400,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _auth_errors(error: Exception) -> HTTPException:
    if isinstance(error, RuntimeStateConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, AuthError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


@router.get("/me", response_model=MeResponse)
def me(request: Request) -> MeResponse:
    """UI hỏi đang đăng nhập với ai và deployment có bắt đăng nhập không."""
    current = settings()
    user = current_user(request)
    return MeResponse(
        auth_required=current.auth_required,
        guest_signup_enabled=current.auth_required and current.auth_guest_signup_enabled,
        user=public(user) if user else None,
        quota=auth_service().guest_quota_summary(user.user_id) if user is not None and user.role == "guest" else None,
    )


@router.post("/login", response_model=PublicUser)
def login(request: LoginRequest, raw: Request, response: Response) -> PublicUser:
    """Đăng nhập; đặt cookie phiên httpOnly."""
    client_limiter.check(_client_key(raw))
    login_limiter.check(request.email.strip().lower())
    try:
        token, user = auth_service().login(request.email, request.password)
    except AuthError as error:
        raise _auth_errors(error) from error
    _set_session_cookie(response, token)
    return public(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    """Xóa phiên phía server và cookie phía trình duyệt."""
    auth_service().logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/register", response_model=PublicUser, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, raw: Request, response: Response) -> PublicUser:
    """Tạo Guest khi không có mã mời, hoặc tài khoản theo lời mời, rồi đăng nhập."""
    if request.invite_code is None:
        return register_guest(
            GuestRegisterRequest(email=request.email, display_name=request.display_name, password=request.password),
            raw,
            response,
        )
    client_limiter.check(_client_key(raw))
    service = auth_service()
    try:
        user = service.register(request.invite_code, request.email, request.display_name, request.password)
        token, user = service.login(user.email, request.password)
    except (AuthError, RuntimeStateConflictError, ValueError) as error:
        raise _auth_errors(error) from error
    _set_session_cookie(response, token)
    return public(user)


@router.post("/register/guest", response_model=PublicUser, status_code=status.HTTP_201_CREATED)
def register_guest(request: GuestRegisterRequest, raw: Request, response: Response) -> PublicUser:
    """Public signup creates only a Guest and can be explicitly disabled."""
    current = settings()
    if not current.auth_required or not current.auth_guest_signup_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Đăng ký Guest hiện chưa được mở")
    client_limiter.check(_client_key(raw))
    service = auth_service()
    try:
        user = service.register_guest(request.email, request.display_name, request.password)
        token, user = service.login(user.email, request.password)
    except (AuthError, RuntimeStateConflictError, ValueError) as error:
        raise _auth_errors(error) from error
    _set_session_cookie(response, token)
    return public(user)


@router.post("/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(request: InviteRequest, actor: UserRecord | None = Depends(require_reviewer)) -> InviteResponse:
    """Reviewer phát mã mời một lần cho Editor hoặc Reviewer."""
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Deployment chưa bật đăng nhập (AUTH_REQUIRED)"
        )
    code, invite = auth_service().create_invite(actor, request.role)
    return InviteResponse(code=code, role=invite.role, expires_at=invite.expires_at.isoformat())


@router.get("/users", response_model=list[PublicUser])
def list_users(_: UserRecord | None = Depends(require_reviewer)) -> list[PublicUser]:
    """Danh sách tài khoản (Reviewer)."""
    return [public(user) for user in auth_service().list_users()]


@router.patch("/users/{user_id}", response_model=PublicUser)
def update_user(user_id: str, request: UserUpdate, actor: UserRecord | None = Depends(require_reviewer)) -> PublicUser:
    """Reviewer đổi role/khóa/hạn mức; không tự hạ quyền hay tự khóa."""
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Deployment chưa bật đăng nhập (AUTH_REQUIRED)"
        )
    try:
        user = auth_service().update_user(
            actor, user_id, role=request.role, active=request.active, daily_job_quota=request.daily_job_quota
        )
    except (AuthError, LookupError) as error:
        raise _auth_errors(error) from error
    return public(user)


@router.get("/audit", response_model=list[AuditEntry])
def audit_log(limit: int = 100, _: UserRecord | None = Depends(require_reviewer)) -> list[AuditEntry]:
    """Nhật ký thao tác mới nhất (Reviewer)."""
    return auth_service().recent_audit(min(max(limit, 1), 500))
