"""Revision invalidation rules for scene edits, và quy tắc nhận biết báo cáo validation có chạy Isaac thật."""

from src.models.contracts.artifacts import Checksum, Identifier
from src.models.contracts.release import SceneRevisionRecord, SceneRevisionStatus
from src.models.contracts.validation import ValidationReport

#: Giá trị bắt đầu bằng các dấu này trong `environment_versions` nghĩa là runtime chưa được xác nhận
#: (Execution Contract: runtime manifest ghi `UNVERIFIED/TBD` cho tới khi provisioning xong).
_UNVERIFIED_MARKERS = ("UNVERIFIED", "TBD")


def has_isaac_runtime_proof(report: ValidationReport) -> bool:
    """Báo cáo có ghi phiên bản Isaac Sim đã chạy thật hay không.

    Thiếu khoá `isaac_sim`, hoặc giá trị bắt đầu bằng `UNVERIFIED`/`TBD` (vd `UNVERIFIED (local environment)` mà
    validator SIM-06 ghi khi máy không có Isaac), nghĩa là kết quả không đến từ simulator thật. UI phải nói rõ
    điều đó thay vì chỉ hiện PASS: một report PASS của fixture rất dễ bị đọc thành "đã chạy simulator".
    """
    version = report.environment_versions.get("isaac_sim", "").strip().upper()
    return bool(version) and not version.startswith(_UNVERIFIED_MARKERS)


def invalidate_after_scene_edit(
    current: SceneRevisionRecord,
    new_revision: Identifier,
    new_scene_ir_checksum: Checksum,
) -> SceneRevisionRecord:
    """Create a DRAFT revision and discard all old derived approvals/reports."""
    if new_revision == current.scene_revision:
        raise ValueError("scene edit must create a new revision")
    if new_scene_ir_checksum == current.scene_ir_checksum:
        raise ValueError("scene edit must change the SceneIR content checksum")
    return SceneRevisionRecord(
        schema_version=current.schema_version,
        scene_id=current.scene_id,
        scene_revision=new_revision,
        scene_ir_checksum=new_scene_ir_checksum,
        status=SceneRevisionStatus.DRAFT,
    )
