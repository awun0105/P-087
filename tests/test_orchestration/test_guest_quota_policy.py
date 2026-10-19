from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.services.orchestration.auth.quota import (
    GuestQuotaExceededDetail,
    GuestQuotaSummary,
    GuestQuotaWindow,
    guest_quota_window,
)


def test_guest_quota_window_uses_vietnam_calendar_day_before_midnight() -> None:
    window = guest_quota_window(datetime(2026, 10, 7, 16, 59, 59, tzinfo=UTC))

    assert window.window_start_utc == datetime(2026, 10, 6, 17, tzinfo=UTC)
    assert window.resets_at_utc == datetime(2026, 10, 7, 17, tzinfo=UTC)


def test_guest_quota_window_moves_at_vietnam_midnight_boundary() -> None:
    window = guest_quota_window(datetime(2026, 10, 7, 17, tzinfo=UTC))

    assert window.window_start_utc == datetime(2026, 10, 7, 17, tzinfo=UTC)
    assert window.resets_at_utc == datetime(2026, 10, 8, 17, tzinfo=UTC)


def test_guest_quota_window_accepts_other_aware_timezone_without_host_timezone() -> None:
    window = guest_quota_window(datetime.fromisoformat("2026-10-08T00:00:00+07:00"))

    assert window.window_start_utc == datetime(2026, 10, 7, 17, tzinfo=UTC)
    assert window.resets_at_utc == datetime(2026, 10, 8, 17, tzinfo=UTC)


def test_guest_quota_window_rejects_naive_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        guest_quota_window(datetime(2026, 10, 8, 0, 0))


def test_quota_summary_and_exhaustion_detail_have_stable_contract() -> None:
    window = guest_quota_window(datetime(2026, 10, 7, 17, tzinfo=UTC))
    summary = GuestQuotaSummary(**window.model_dump(), used=3, remaining=0)
    detail = GuestQuotaExceededDetail(quota=summary)

    assert detail.model_dump(mode="json") == {
        "code": "guest_daily_job_quota_exceeded",
        "quota": {
            "policy_id": "guest_calendar_day_v1",
            "limit": 3,
            "timezone": "Asia/Ho_Chi_Minh",
            "window_start_utc": "2026-10-07T17:00:00Z",
            "resets_at_utc": "2026-10-08T17:00:00Z",
            "used": 3,
            "remaining": 0,
        },
    }


def test_quota_contract_rejects_inconsistent_remaining_and_non_utc_boundaries() -> None:
    window = guest_quota_window(datetime(2026, 10, 7, 17, tzinfo=UTC))

    with pytest.raises(ValidationError, match="remaining must equal"):
        GuestQuotaSummary(**window.model_dump(), used=3, remaining=1)
    with pytest.raises(ValidationError, match="must use UTC"):
        GuestQuotaWindow(
            window_start_utc=datetime.fromisoformat("2026-10-08T00:00:00+07:00"),
            resets_at_utc=window.resets_at_utc,
        )
    with pytest.raises(ValidationError, match="Vietnam midnight"):
        GuestQuotaWindow(
            window_start_utc=datetime(2026, 10, 7, 16, tzinfo=UTC),
            resets_at_utc=window.resets_at_utc,
        )
    with pytest.raises(ValidationError, match="exhausted quota"):
        GuestQuotaExceededDetail(
            quota=GuestQuotaSummary(**window.model_dump(), used=1, remaining=2),
        )
