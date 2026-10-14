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


def _project(result: PrivacyResult, mode: str, findings: bool = False, **attestation: bool):  # noqa: ANN202
    from src.models.contracts.identity import canonical_content_checksum
    from src.models.contracts.manifests import PrivacyValidationReport
    from src.services.orchestration.projects.models import ProjectRecord

    payload = dict(
        schema_version="1.0",
        input_manifest_checksum="sha256:" + "a" * 64,
        inspection_scope="sampled",
        selected_frame_count=3,
        inspected_frame_count=0 if not findings else 1,
        unresolved_findings=[{"frame": 1}] if findings else [],
        result=result,
        report_checksum="sha256:" + "0" * 64,
    )
    payload["report_checksum"] = canonical_content_checksum(payload, "report_checksum")
    flags = {"rights_to_use_confirmed": True, "anonymization_confirmed": True, **attestation}
    return ProjectRecord(
        project_id="project-x",
        name="x",
        source_type="upload",
        input_manifest_checksum="sha256:" + "a" * 64,
        source_rights_attestation=flags,
        privacy_report=PrivacyValidationReport.model_validate(payload),
        privacy_mode=mode,
    )


def test_self_attested_project_dispatches_without_qa() -> None:
    from src.services.orchestration.projects.privacy import project_dispatch_allowed, require_project_dispatch

    project = _project(PrivacyResult.PRELIMINARY_SCREENED, "self_attested")
    assert project_dispatch_allowed(project)
    require_project_dispatch(project)


@pytest.mark.parametrize(
    ("result", "mode", "findings", "flags"),
    [
        (PrivacyResult.PRELIMINARY_SCREENED, "qa_verified", False, {}),
        (PrivacyResult.QUARANTINED, "self_attested", False, {}),
        (PrivacyResult.PRELIMINARY_SCREENED, "self_attested", True, {}),
        (PrivacyResult.PRELIMINARY_SCREENED, "self_attested", False, {"anonymization_confirmed": False}),
    ],
)
def test_project_dispatch_blocks_without_valid_self_attestation(
    result: PrivacyResult, mode: str, findings: bool, flags: dict[str, bool]
) -> None:
    from src.services.orchestration.projects.privacy import project_dispatch_allowed, require_project_dispatch

    project = _project(result, mode, findings, **flags)
    assert not project_dispatch_allowed(project)
    with pytest.raises(PrivacyGateBlockedError):
        require_project_dispatch(project)


def test_qa_verified_admits_only_studio_video_uploads_which_the_worker_masks() -> None:
    """Video upload ở `qa_verified` vào hàng đợi (worker che + chờ chấp nhận); loại project khác vẫn cần VERIFIED."""
    from src.services.orchestration.projects.models import InputVideoSummary
    from src.services.orchestration.projects.privacy import project_block_reason, project_dispatch_allowed

    other = _project(PrivacyResult.PRELIMINARY_SCREENED, "qa_verified")
    video = other.model_copy(
        update={"input_video": InputVideoSummary(original_name="a.mp4", media_type="video/mp4", size_bytes=1)}
    )
    assert not project_dispatch_allowed(other) and project_dispatch_allowed(video)
    unattested = _project(PrivacyResult.PRELIMINARY_SCREENED, "qa_verified", anonymization_confirmed=False)
    unattested = unattested.model_copy(update={"input_video": video.input_video})
    assert project_block_reason(unattested) is not None
    quarantined = _project(PrivacyResult.QUARANTINED, "qa_verified").model_copy(
        update={"input_video": video.input_video}
    )
    assert not project_dispatch_allowed(quarantined)
