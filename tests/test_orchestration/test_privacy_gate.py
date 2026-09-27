"""Unit tests for privacy gate rules.

Tests are data-only: no I/O, no fixtures on disk.
Matches the PRODUCT-01 §10 requirement for QUARANTINED/missing-rights dispatch
negative tests.
"""

import pytest

from src.models.contracts.manifests import PrivacyResult
from src.services.orchestration.projects.errors import PrivacyGateBlockedError
from src.services.orchestration.projects.privacy import (
    DISPATCH_CLEARED,
    block_reason,
    dispatch_allowed,
    require_dispatch_allowed,
)


@pytest.mark.parametrize("result", [PrivacyResult.VERIFIED_ANONYMIZED])
def test_dispatch_allowed_for_cleared_states(result: PrivacyResult) -> None:
    assert dispatch_allowed(result) is True


@pytest.mark.parametrize("result", [PrivacyResult.QUARANTINED, PrivacyResult.PRELIMINARY_SCREENED])
def test_dispatch_blocked_for_non_cleared_states(result: PrivacyResult) -> None:
    assert dispatch_allowed(result) is False


@pytest.mark.parametrize("result", [PrivacyResult.QUARANTINED, PrivacyResult.PRELIMINARY_SCREENED])
def test_block_reason_returns_none_only_when_allowed(result: PrivacyResult) -> None:
    reason = block_reason(result)
    assert reason is not None
    assert len(reason) > 0


def test_block_reason_is_none_for_cleared() -> None:
    assert block_reason(PrivacyResult.VERIFIED_ANONYMIZED) is None


def test_require_raises_for_quarantined() -> None:
    with pytest.raises(PrivacyGateBlockedError, match="không thể tạo job"):
        require_dispatch_allowed(PrivacyResult.QUARANTINED)


def test_require_raises_for_preliminary() -> None:
    with pytest.raises(PrivacyGateBlockedError):
        require_dispatch_allowed(PrivacyResult.PRELIMINARY_SCREENED)


def test_require_does_not_raise_for_verified() -> None:
    require_dispatch_allowed(PrivacyResult.VERIFIED_ANONYMIZED)  # must not raise


def test_dispatch_cleared_frozenset_contents() -> None:
    assert PrivacyResult.VERIFIED_ANONYMIZED in DISPATCH_CLEARED
    assert PrivacyResult.QUARANTINED not in DISPATCH_CLEARED
    assert PrivacyResult.PRELIMINARY_SCREENED not in DISPATCH_CLEARED
