"""Region boxes → Gaussian membership for one object (T-004). Pure functions: no I/O, no scene state."""

import math
from dataclasses import dataclass

import numpy as np

from src.models.contracts.coordinates import Transform
from src.models.contracts.object_membership import ObjectMembershipArtifact, ObjectRegionCommand, RegionBox
from src.services.reconstruction.alignment.similarity import rotation_matrix
from src.services.scene.editing.membership import ObjectMembershipValidationError

#: Dung sai tuyệt đối khi kiểm điểm nằm trên mặt box; khớp `CONTAINS_TOLERANCE_M` của frontend (box-model.ts).
CONTAINS_TOLERANCE_M = 1e-6
#: Nhãn nền trong membership (`-1`), khớp `_BACKGROUND_LABEL` của membership.py.
BACKGROUND_LABEL = -1
#: Vật còn dưới mức này sau khi áp box bị từ chối; người dùng nên xoá vật thay vì thu box.
MIN_OBJECT_ROWS = 50


#: Biên an toàn cho lọc sơ bộ theo hình vuông bao quanh box; lớn hơn sai số làm tròn, nhỏ hơn mọi kích thước thật.
_NEAR_SLACK_M = 1e-9
#: Dưới tỉ lệ này thì chỉ tính trên ứng viên; trên thì tính trên cả đám mây (sao chép ứng viên tốn hơn khi chúng nhiều).
_CANDIDATE_SHARE_LIMIT = 4


def _box_contains(points_local: np.ndarray, box: RegionBox) -> np.ndarray:
    center = np.asarray(box.center_m, dtype=float)
    half = np.asarray(box.half_extents_m, dtype=float)
    cos_yaw, sin_yaw = math.cos(box.yaw_rad), math.sin(box.yaw_rad)
    # Điểm trong box có khoảng cách ngang tới tâm không quá bán kính ngang, bất kể yaw; các điểm còn lại chắc chắn ngoài box.
    # Khi chỉ một phần nhỏ đám mây là ứng viên thì công thức đầy đủ chỉ chạy trên ứng viên (T-025); khi phần lớn là ứng viên
    # thì chạy trên cả đám mây như trước, vì sao chép ứng viên tốn hơn.
    reach = math.hypot(half[0] + CONTAINS_TOLERANCE_M, half[1] + CONTAINS_TOLERANCE_M) + _NEAR_SLACK_M
    # Điểm không hữu hạn cho inf × 0 = NaN; so sánh với NaN luôn sai nên điểm rơi vào "ngoài box" như mong muốn.
    with np.errstate(invalid="ignore"):
        near = (np.abs(points_local[:, 0] - center[0]) <= reach) & (np.abs(points_local[:, 1] - center[1]) <= reach)
        candidates = np.flatnonzero(near)
        if candidates.size == 0:
            return np.zeros(len(points_local), dtype=bool)
        selective = candidates.size * _CANDIDATE_SHARE_LIMIT < len(points_local)
        subset = points_local[candidates] if selective else points_local
        relative = subset - center
        along_x = relative[:, 0] * cos_yaw + relative[:, 1] * sin_yaw
        along_y = -relative[:, 0] * sin_yaw + relative[:, 1] * cos_yaw
        along_z = relative[:, 2]
        contained = (
            (np.abs(along_x) <= half[0] + CONTAINS_TOLERANCE_M)
            & (np.abs(along_y) <= half[1] + CONTAINS_TOLERANCE_M)
            & (np.abs(along_z) <= half[2] + CONTAINS_TOLERANCE_M)
        )
    if not selective:
        return contained
    inside = np.zeros(len(points_local), dtype=bool)
    inside[candidates] = contained
    return inside


def boxes_contain(points_local: np.ndarray, boxes: list[RegionBox]) -> np.ndarray:
    """inside = ∪ add \\ ∪ subtract; điểm trên mặt box tính là bên trong (dung sai 1e-6)."""
    inside = np.zeros(len(points_local), dtype=bool)
    for box in boxes:
        if box.op == "add":
            inside |= _box_contains(points_local, box)
    for box in boxes:
        if box.op == "subtract":
            inside &= ~_box_contains(points_local, box)
    return inside


@dataclass(frozen=True)
class RegionResolution:
    """Kết quả áp box lên một vật: hàng thuộc vật sau khi áp, hàng thêm/bớt và thống kê cho preview."""

    object_mask: np.ndarray  # bool (gaussian_count,)
    added: np.ndarray  # int64: source row được thêm vào vật
    removed: np.ndarray  # int64: source row bị trả về nền
    claimed: dict[str, int]  # object_id → số hàng lấy từ vật đó
    overlaps: dict[str, int]  # object_id → số hàng vật đó nằm trong box nhưng không được lấy
    protected_floor_count: int  # số hàng sàn nằm trong box mà không được lấy


def _labels_of(manifest: ObjectMembershipArtifact, object_id: str) -> list[int]:
    labels = [int(label) for label, owner in manifest.label_to_object_id.items() if owner == object_id]
    if not labels:
        raise ObjectMembershipValidationError(f"vật {object_id} không có trong membership")
    return labels


def resolve_region(
    *,
    positions_world: np.ndarray,
    labels: np.ndarray,
    manifest: ObjectMembershipArtifact,
    object_id: str,
    source_world_from_object: Transform,
    command: ObjectRegionCommand,
    floor_protected: np.ndarray | None,
    points_local: np.ndarray | None = None,
) -> RegionResolution:
    """Hàng mới = inside ∩ eligible; eligible = nền không thuộc sàn ∪ hàng của vật ∪ hàng của vật trong claim_from.

    Box là object-local. Đổi sang world bằng pose nguồn lúc tách (`source_world_from_object`), không dùng pose hiện tại.
    `points_local` truyền vào khi người gọi đã đổi sang object-local (cùng pose), để không đổi hai lần.
    """
    count = manifest.gaussian_count
    if positions_world.shape != (count, 3) or not np.isfinite(positions_world).all():
        raise ObjectMembershipValidationError("source Gaussian positions do not match membership")
    if labels.shape != (count,):
        raise ObjectMembershipValidationError("membership labels must be one integer per source Gaussian row")
    floor = np.zeros(count, dtype=bool) if floor_protected is None else np.asarray(floor_protected, dtype=bool)
    if floor.shape != (count,):
        raise ObjectMembershipValidationError("floor protection must be one flag per source Gaussian row")
    if object_id in command.claim_from:
        raise ObjectMembershipValidationError("claim_from không được chứa chính vật đang sửa")

    own_labels = _labels_of(manifest, object_id)
    claimed_ids = list(command.claim_from)
    claim_labels = [label for other in claimed_ids for label in _labels_of(manifest, other)]

    if points_local is None:
        rotation = rotation_matrix(source_world_from_object.rotation_quaternion_xyzw)
        translation = np.asarray(source_world_from_object.translation_xyz, dtype=float)
        points_local = (positions_world - translation) @ rotation
    inside = boxes_contain(points_local, command.boxes)

    own = np.isin(labels, own_labels)
    background = labels == BACKGROUND_LABEL
    eligible = (background & ~floor) | own | np.isin(labels, claim_labels)
    object_mask = inside & eligible
    added = np.flatnonzero(object_mask & ~own)
    removed = np.flatnonzero(own & ~object_mask)
    object_rows = int(np.count_nonzero(object_mask))
    if object_rows < MIN_OBJECT_ROWS:
        raise ObjectMembershipValidationError(
            f"vật còn {object_rows} Gaussian sau khi áp box (tối thiểu {MIN_OBJECT_ROWS}); dùng Xoá vật thay vì thu box"
        )

    claimed: dict[str, int] = {}
    for other in claimed_ids:
        taken = int(np.count_nonzero(np.isin(labels[added], _labels_of(manifest, other))))
        if taken:
            claimed[other] = taken
    overlaps: dict[str, int] = {}
    inside_labels = labels[inside]
    for label, owner in manifest.label_to_object_id.items():
        if owner == object_id or owner in claimed_ids:
            continue
        hits = int(np.count_nonzero(inside_labels == int(label)))
        if hits:
            overlaps[owner] = overlaps.get(owner, 0) + hits
    return RegionResolution(
        object_mask=object_mask,
        added=added,
        removed=removed,
        claimed=claimed,
        overlaps=overlaps,
        protected_floor_count=int(np.count_nonzero(inside & background & floor)),
    )


def apply_resolution(
    labels: np.ndarray, manifest: ObjectMembershipArtifact, object_id: str, resolution: RegionResolution
) -> np.ndarray:
    """Nhãn mới: hàng thêm vào nhận nhãn nhỏ nhất của vật; hàng bớt về -1. Không sửa mảng đầu vào."""
    updated = labels.copy()
    updated[resolution.added] = min(_labels_of(manifest, object_id))
    updated[resolution.removed] = BACKGROUND_LABEL
    return updated


def preview_payload(resolution: RegionResolution, positions_local: np.ndarray, sample_limit: int = 20_000) -> dict:
    """Thống kê và mẫu toạ độ object-local cho preview. Mẫu lấy đều theo chỉ số nên cùng đầu vào cho cùng kết quả."""
    return {
        "added_count": int(resolution.added.size),
        "removed_count": int(resolution.removed.size),
        "object_gaussian_count": int(np.count_nonzero(resolution.object_mask)),
        "protected_floor_count": resolution.protected_floor_count,
        "overlaps": dict(resolution.overlaps),
        "claimed": dict(resolution.claimed),
        "added_sample_m": _even_sample(positions_local[resolution.added], sample_limit),
        "removed_sample_m": _even_sample(positions_local[resolution.removed], sample_limit),
    }


def _even_sample(points: np.ndarray, limit: int) -> list[list[float]]:
    if len(points) <= limit:
        return points.tolist()
    indices = np.linspace(0, len(points) - 1, num=limit).round().astype(np.int64)
    return points[indices].tolist()
