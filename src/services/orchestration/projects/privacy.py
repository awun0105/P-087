"""Privacy gate rules for product dispatch.

EX-PRODUCT thu source-rights attestation và hiển thị privacy state. Ở P0 chưa có
`ST-PRIVACY-GATE` thật (do EX-REC sở hữu), nên module này chỉ mã hoá luật đã được
chốt: chỉ `VERIFIED_ANONYMIZED` mới cho phép dispatch.
"""

from typing import TYPE_CHECKING

from src.models.contracts.manifests import PrivacyResult
from src.services.orchestration.projects.errors import PrivacyGateBlockedError

if TYPE_CHECKING:
    from src.services.orchestration.projects.models import ProjectRecord

#: Trạng thái duy nhất cho phép đưa input vào pipeline. QA/Validation Lead chấp
#: nhận `VERIFIED_ANONYMIZED` trước public/demo use — automation không tự nâng cấp.
DISPATCH_CLEARED: frozenset[PrivacyResult] = frozenset({PrivacyResult.VERIFIED_ANONYMIZED})

_HUMAN_REASON: dict[PrivacyResult, str] = {
    PrivacyResult.QUARANTINED: "input bị quarantine: còn thông tin nhận dạng chưa xử lý",
    PrivacyResult.PRELIMINARY_SCREENED: "input mới ở mức sàng lọc sơ bộ, chưa được QA xác nhận ẩn danh",
}


def dispatch_allowed(result: PrivacyResult) -> bool:
    """True only when the privacy state clears the input for pipeline dispatch."""
    return result in DISPATCH_CLEARED


def block_reason(result: PrivacyResult) -> str | None:
    """Human-readable Vietnamese reason, or None when dispatch is allowed."""
    if dispatch_allowed(result):
        return None
    return _HUMAN_REASON.get(result, f"privacy state {result} không cho phép dispatch")


def require_dispatch_allowed(result: PrivacyResult) -> None:
    """Raise PrivacyGateBlockedError unless the input may enter the pipeline."""
    reason = block_reason(result)
    if reason is not None:
        raise PrivacyGateBlockedError(f"không thể tạo job: {reason}")


#: Cờ tự khai bắt buộc trong `source_rights_attestation` cho chế độ MVP.
SELF_ATTESTATION_FLAGS = ("rights_to_use_confirmed", "anonymization_confirmed")


def project_block_reason(project: "ProjectRecord") -> str | None:
    """Lý do chặn dispatch của một project, hoặc None khi được chạy.

    `self_attested` (MVP, owner chốt 2026-09-29): người upload đã tự xác nhận video
    không chứa khuôn mặt/biển số. Chỉ chấp nhận khi report còn ở mức sàng lọc sơ
    bộ, không có finding; `QUARANTINED` luôn chặn. Không nâng report thành VERIFIED.
    """
    report = project.privacy_report
    if project.privacy_mode == "self_attested" and report.result == PrivacyResult.PRELIMINARY_SCREENED:
        attestation = project.source_rights_attestation
        if report.unresolved_findings:
            return "input có finding privacy chưa xử lý"
        if any(attestation.get(flag) is not True for flag in SELF_ATTESTATION_FLAGS):
            return "người upload chưa xác nhận quyền dùng và việc ẩn danh khuôn mặt/biển số"
        return None
    return block_reason(report.result)


def project_dispatch_allowed(project: "ProjectRecord") -> bool:
    """True khi project được phép đưa input vào pipeline."""
    return project_block_reason(project) is None


def require_project_dispatch(project: "ProjectRecord") -> None:
    """Raise PrivacyGateBlockedError khi project chưa được phép dispatch."""
    reason = project_block_reason(project)
    if reason is not None:
        raise PrivacyGateBlockedError(f"không thể tạo job: {reason}")
