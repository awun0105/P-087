"""Lọc prompt, bỏ phiếu 3D và gộp instance — ADAPT từ SAMPro3D `main.py` (R2G, Apache-2.0).

Bản gốc: `prompt_filter` (IoU/ổn định + NMS + tỉ lệ frame đồng ý), `perform_3dsegmentation`
(điểm 3D được mask bỏ phiếu qua nhiều frame), `prompt_consolidation` (DBSCAN dọn nhiễu, gộp
prompt cùng vật), sàn tách bằng RANSAC. Khác bản gốc: DBSCAN bằng đồ thị bán kính của
`scipy.spatial.cKDTree`; sàn = z = 0 đã xác nhận ở REC-06 thay RANSAC; không cần CUDA ext.
"""

from dataclasses import dataclass, field

import numpy as np
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


@dataclass(frozen=True)
class Sampro3dConfig:
    """Ngưỡng theo mặc định SAMPro3D (`main.py:get_args`) khi có tương đương."""

    prompt_voxel_m: float = 0.2
    max_prompts: int = 400
    floor_band_m: float = 0.08
    pred_iou_thres: float = 0.7
    mask_nms_thres: float = 0.8
    keep_thres: float = 0.4
    min_mask_points: int = 10
    min_views: int = 2
    vote_thres: float = 0.5
    merge_thres: float = 0.5
    cluster_radius_m: float = 0.15
    min_instance_points: int = 30


@dataclass(frozen=True)
class Proposal:
    """Kết quả bước SAM2: mỗi record = (frame, prompt, iou, điểm 3D trong mask)."""

    view: np.ndarray
    prompt: np.ndarray
    iou: np.ndarray
    members: list[np.ndarray]
    visible: list[np.ndarray] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "Proposal":
        data = np.load(path)
        offsets, members = data["offsets"], data["members"]
        vis_offsets, vis_members = data["visible_offsets"], data["visible_members"]
        return cls(
            view=data["view"],
            prompt=data["prompt"],
            iou=data["iou"],
            members=[members[offsets[i] : offsets[i + 1]] for i in range(len(offsets) - 1)],
            visible=[vis_members[vis_offsets[i] : vis_offsets[i + 1]] for i in range(len(vis_offsets) - 1)],
        )


def farthest_point_sampling(points: np.ndarray, count: int, seed: int = 0) -> np.ndarray:
    """FPS (thay `pointops.farthest_point_sampling`), bắt đầu từ điểm cố định để tái lập."""
    if count >= len(points):
        return np.arange(len(points))
    chosen = np.empty(count, dtype=np.int64)
    chosen[0] = seed % len(points)
    distance = np.linalg.norm(points - points[chosen[0]], axis=1)
    for index in range(1, count):
        chosen[index] = int(distance.argmax())
        distance = np.minimum(distance, np.linalg.norm(points - points[chosen[index]], axis=1))
    return chosen


def select_prompts(points: np.ndarray, config: Sampro3dConfig = Sampro3dConfig()) -> np.ndarray:
    """Số prompt = số voxel `prompt_voxel_m` có điểm (như SAMPro3D), bỏ sàn, chặn trên `max_prompts`."""
    above = np.nonzero(points[:, 2] > config.floor_band_m)[0]
    if not len(above):
        return above
    voxels = np.unique(np.floor(points[above] / config.prompt_voxel_m).astype(np.int64), axis=0)
    count = min(len(voxels), config.max_prompts)
    return above[farthest_point_sampling(points[above], count)]


def _jaccard(a: np.ndarray, b: np.ndarray) -> float:
    if not len(a) or not len(b):
        return 0.0
    inter = len(np.intersect1d(a, b, assume_unique=True))
    return inter / (len(a) + len(b) - inter)


def _surviving_records(proposal: Proposal, config: Sampro3dConfig) -> list[int]:
    """Mask đạt IoU dự đoán, đủ điểm; NMS trong cùng frame theo tập điểm (thay box NMS)."""
    good = [
        i
        for i in range(len(proposal.iou))
        if proposal.iou[i] >= config.pred_iou_thres and len(proposal.members[i]) >= config.min_mask_points
    ]
    kept: list[int] = []
    for view in np.unique(proposal.view[good]) if good else []:
        in_view = sorted((i for i in good if proposal.view[i] == view), key=lambda i: -proposal.iou[i])
        chosen: list[int] = []
        for record in in_view:
            if all(
                _jaccard(proposal.members[record], proposal.members[other]) < config.mask_nms_thres for other in chosen
            ):
                chosen.append(record)
        kept.extend(chosen)
    return kept


def segment(proposal: Proposal, points: np.ndarray, config: Sampro3dConfig = Sampro3dConfig()) -> list[np.ndarray]:
    """Trả danh sách instance (chỉ số điểm), đã dọn nhiễu và bỏ sàn."""
    kept = _surviving_records(proposal, config)
    prompts = np.unique(proposal.prompt)
    visible_per_prompt = {p: int((proposal.prompt == p).sum()) for p in prompts}
    kept_per_prompt: dict[int, list[int]] = {}
    for record in kept:
        kept_per_prompt.setdefault(int(proposal.prompt[record]), []).append(record)
    valid = [
        p
        for p, records in kept_per_prompt.items()
        if len(records) >= config.min_views and len(records) / visible_per_prompt[p] >= config.keep_thres
    ]
    if not valid:
        return []
    # Bỏ phiếu: điểm được mask của prompt p "chọn" / số frame p và điểm cùng được nhìn thấy.
    column = {p: i for i, p in enumerate(valid)}
    hits = np.zeros((len(valid), len(points)), dtype=np.float32)
    seen = np.zeros_like(hits)
    for p in valid:
        for record in kept_per_prompt[p]:
            hits[column[p], proposal.members[record]] += 1
            if proposal.visible:
                seen[column[p], proposal.visible[int(proposal.view[record])]] += 1
    score = np.divide(hits, seen, out=np.zeros_like(hits), where=seen >= config.min_views)
    owner = score.argmax(axis=0)
    confident = score.max(axis=0) >= config.vote_thres
    supports = [np.nonzero(confident & (owner == column[p]))[0] for p in valid]
    # Gộp prompt cùng vật (union-find theo độ chồng tập điểm hỗ trợ).
    parent = list(range(len(valid)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    strong = np.nonzero(score >= config.vote_thres)
    per_prompt = [strong[1][strong[0] == i] for i in range(len(valid))]
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            if _jaccard(per_prompt[i], per_prompt[j]) >= config.merge_thres:
                parent[find(i)] = find(j)
    groups: dict[int, list[np.ndarray]] = {}
    for i, support in enumerate(supports):
        groups.setdefault(find(i), []).append(support)
    instances = []
    for parts in groups.values():
        members = np.unique(np.concatenate(parts))
        members = members[points[members, 2] > config.floor_band_m]
        cleaned = _largest_cluster(points, members, config)
        if len(cleaned) >= config.min_instance_points:
            instances.append(cleaned)
    return sorted(instances, key=len, reverse=True)


def _largest_cluster(points: np.ndarray, members: np.ndarray, config: Sampro3dConfig) -> np.ndarray:
    """Tương đương DBSCAN dọn nhiễu: giữ thành phần liên thông lớn nhất theo bán kính."""
    if len(members) < config.min_instance_points:
        return members[:0]
    pairs = cKDTree(points[members]).query_pairs(config.cluster_radius_m, output_type="ndarray")
    if not len(pairs):
        return members[:0]
    from scipy.sparse import coo_matrix

    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(members), len(members)))
    count, labels = connected_components(graph, directed=False)
    largest = np.bincount(labels).argmax()
    return members[labels == largest]
