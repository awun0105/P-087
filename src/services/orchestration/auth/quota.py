"""Guest calendar-day quota contracts and deterministic Vietnam windowing."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

GUEST_QUOTA_POLICY_ID = "guest_calendar_day_v1"
GUEST_QUOTA_LIMIT = 3
GUEST_QUOTA_TIMEZONE = "Asia/Ho_Chi_Minh"
_GUEST_TIMEZONE = ZoneInfo(GUEST_QUOTA_TIMEZONE)


class GuestQuotaWindow(BaseModel):
    """One policy window, stored and returned as UTC boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: Literal["guest_calendar_day_v1"] = GUEST_QUOTA_POLICY_ID
    limit: Literal[3] = GUEST_QUOTA_LIMIT
    timezone: Literal["Asia/Ho_Chi_Minh"] = GUEST_QUOTA_TIMEZONE
    window_start_utc: datetime
    resets_at_utc: datetime

    @model_validator(mode="after")
    def _utc_window_is_ordered(self) -> "GuestQuotaWindow":
        start = self.window_start_utc
        end = self.resets_at_utc
        if start.tzinfo is None or start.utcoffset() is None or end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("Quota window timestamps must be timezone-aware")
        if start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0):
            raise ValueError("Quota window timestamps must use UTC")
        if start >= end:
            raise ValueError("Quota window must be a non-empty half-open interval")
        local_start = start.astimezone(_GUEST_TIMEZONE)
        local_end = end.astimezone(_GUEST_TIMEZONE)
        if local_start.time() != time.min or local_end.time() != time.min:
            raise ValueError("Quota window boundaries must be Vietnam midnight")
        if local_end.date() != local_start.date() + timedelta(days=1):
            raise ValueError("Quota window must cover exactly one Vietnam calendar day")
        return self


class GuestQuotaSummary(GuestQuotaWindow):
    """Typed summary for `/auth/me` once the durable ledger is implemented."""

    used: int = Field(ge=0)
    remaining: int = Field(ge=0, le=GUEST_QUOTA_LIMIT)

    @model_validator(mode="after")
    def _remaining_matches_usage(self) -> "GuestQuotaSummary":
        if self.remaining != max(self.limit - self.used, 0):
            raise ValueError("remaining must equal the unused portion of the daily quota")
        return self


class GuestQuotaExceededDetail(BaseModel):
    """Stable 429 detail; clients branch on `code`, never message text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal["guest_daily_job_quota_exceeded"] = "guest_daily_job_quota_exceeded"
    quota: GuestQuotaSummary

    @model_validator(mode="after")
    def _quota_is_exhausted(self) -> "GuestQuotaExceededDetail":
        if self.quota.remaining != 0:
            raise ValueError("Quota-exceeded detail requires an exhausted quota")
        return self


def guest_quota_window(now: datetime | None = None) -> GuestQuotaWindow:
    """Return `[Vietnam midnight, next Vietnam midnight)` converted to UTC.

    `now` exists as a deterministic test seam. Production callers omit it and use
    the server clock in UTC; naive datetimes are rejected to avoid host-timezone
    interpretation.
    """
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Quota clock input must be timezone-aware")

    local_date: date = instant.astimezone(_GUEST_TIMEZONE).date()
    next_date = local_date + timedelta(days=1)
    start_local = datetime.combine(local_date, time.min, tzinfo=_GUEST_TIMEZONE)
    end_local = datetime.combine(next_date, time.min, tzinfo=_GUEST_TIMEZONE)
    return GuestQuotaWindow(
        window_start_utc=start_local.astimezone(UTC),
        resets_at_utc=end_local.astimezone(UTC),
    )
