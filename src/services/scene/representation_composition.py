"""Chính sách representation thuần, độc lập visibility tạm thời của Studio."""

from dataclasses import dataclass
from enum import StrEnum

from src.models.contracts.scene import SceneIR, SceneObject, SceneObjectOrigin, SceneObjectState


class VisualPolicy(StrEnum):
    SOURCE = "source"
    OBJECT = "object"
    OMIT = "omit"


@dataclass(frozen=True)
class RepresentationDisposition:
    object_id: str
    visual_policy: VisualPolicy
    export_as_object: bool
    source_visual_required: bool
    readiness_blockers: tuple[str, ...] = ()


def resolve_representation(obj: SceneObject, *, split_visuals: bool = False) -> RepresentationDisposition:
    """Loại/ứng viên giữ quan sát nguồn; active chỉ điều khiển vật đã xác nhận."""
    review = obj.provenance.get("review")
    blockers: list[str] = []
    if obj.active and (obj.state != SceneObjectState.CONFIRMED or review in {"IGNORED", "DELETED", "MERGED"}):
        blockers.append("INVALID_OBJECT_ACTIVATION")
    if review in {"DELETED", "MERGED"}:
        policy = VisualPolicy.OMIT
    elif obj.state == SceneObjectState.CANDIDATE or review == "IGNORED":
        if obj.origin != SceneObjectOrigin.RECONSTRUCTED or obj.provenance.get("duplicated_from") is not None:
            policy = VisualPolicy.OMIT
            blockers.append("SOURCE_REPRESENTATION_UNSUPPORTED")
        else:
            policy = VisualPolicy.SOURCE
    else:
        policy = VisualPolicy.OBJECT if obj.active else VisualPolicy.OMIT
    gaussian_visual = obj.visual_ref is not None and obj.visual_ref.artifact_type == "ObjectGaussians"
    required = policy == VisualPolicy.SOURCE and (split_visuals or gaussian_visual)
    # Reassign có thể để lại candidate rỗng để audit; membership được kiểm riêng trước export.
    empty = obj.provenance.get("membership_reassign_blocker") == "NO_SOURCE_GAUSSIANS"
    if required and not gaussian_visual and not empty:
        blockers.append("SOURCE_VISUAL_MISSING")
    return RepresentationDisposition(obj.id, policy, policy == VisualPolicy.OBJECT, required, tuple(blockers))


def scene_representations(scene: SceneIR) -> list[RepresentationDisposition]:
    """Context decomposition thuộc revision, không ghi field mới vào SceneIR."""
    split = scene.environment.membership is not None or str(scene.provenance.get("object_extraction", "")).startswith(
        "objectify_v1("
    )
    return [resolve_representation(item, split_visuals=split) for item in scene.objects]
