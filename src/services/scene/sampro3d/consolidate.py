"""Lọc prompt, bỏ phiếu 3D và gộp instance — ADAPT từ SAMPro3D `main.py` (R2G, Apache-2.0).

Bản gốc: `prompt_filter` (IoU/ổn định + NMS + tỉ lệ frame đồng ý), `perform_3dsegmentation`
(điểm 3D được mask bỏ phiếu qua nhiều frame), `prompt_consolidation` (DBSCAN dọn nhiễu, gộp
prompt cùng vật). Floor mask dùng FloorModel bị ràng buộc bởi prior REC-06; DBSCAN
được thay bằng đồ thị bán kính `scipy.spatial.cKDTree`; không cần CUDA ext.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from src.models.contracts.floor_model import FloorModel
from src.services.scene.association.refinement import object_point_mask
from src.services.scene.diagnostics import EvidenceRecorder
from src.services.scene.floor_model import above_floor_mask


@dataclass(frozen=True)
class Sampro3dConfig:
    """Ngưỡng theo mặc định SAMPro3D (`main.py:get_args`) khi có tương đương."""

    prompt_voxel_m: float = 0.2
    max_prompts: int = 400
    pred_iou_thres: float = 0.7
    mask_nms_thres: float = 0.8
    keep_thres: float = 0.4
    min_mask_points: int = 10
    min_views: int = 2
    vote_thres: float = 0.5
    merge_thres: float = 0.5
    cluster_radius_m: float = 0.15
    min_instance_points: int = 30
    refinement: Literal["legacy", "multiview_v1"] = "legacy"


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


def select_prompts(
    points: np.ndarray, floor_model: FloorModel, config: Sampro3dConfig = Sampro3dConfig()
) -> np.ndarray:
    """Số prompt = số voxel có điểm phía trên fitted floor, chặn trên `max_prompts`."""
    eligible = (
        object_point_mask(points, floor_model)
        if config.refinement == "multiview_v1"
        else above_floor_mask(points, floor_model)
    )
    above = np.nonzero(eligible)[0]
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


def _surviving_records(
    proposal: Proposal, config: Sampro3dConfig, evidence: EvidenceRecorder | None = None
) -> list[int]:
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
                (config.refinement == "multiview_v1" and proposal.prompt[record] != proposal.prompt[other])
                or _jaccard(proposal.members[record], proposal.members[other]) < config.mask_nms_thres
                for other in chosen
            ):
                chosen.append(record)
        kept.extend(chosen)
    if evidence is not None:
        good_set, kept_set = set(good), set(kept)
        for i in range(len(proposal.iou)):
            reasons = []
            if not np.isfinite(proposal.iou[i]):
                reasons.append("nonfinite_iou")
            if proposal.iou[i] < config.pred_iou_thres:
                reasons.append("predicted_iou_below_threshold")
            if len(proposal.members[i]) < config.min_mask_points:
                reasons.append("too_few_mask_points")
            if i in good_set and i not in kept_set:
                reasons.append("same_view_nms")
            evidence.emit(
                "mask_decision",
                record=i,
                view=int(proposal.view[i]),
                prompt=int(proposal.prompt[i]),
                predicted_iou=float(proposal.iou[i]),
                points=len(proposal.members[i]),
                accepted=i in kept_set,
                reasons=reasons,
            )
    return kept


def segment(
    proposal: Proposal,
    points: np.ndarray,
    floor_model: FloorModel,
    config: Sampro3dConfig = Sampro3dConfig(),
    *,
    evidence: EvidenceRecorder | None = None,
) -> list[np.ndarray]:
    """Trả danh sách instance (chỉ số điểm), đã dọn nhiễu và bỏ sàn."""
    if config.refinement == "multiview_v1":
        return _segment_multiview(proposal, points, floor_model, config, evidence)
    kept = _surviving_records(proposal, config, evidence)
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
    if evidence is not None:
        from dataclasses import asdict

        evidence.emit("config", thresholds=asdict(config), input_points=len(points))
        for p in prompts:
            count = len(kept_per_prompt.get(p, []))
            evidence.emit(
                "prompt_decision",
                prompt=int(p),
                observations=visible_per_prompt[p],
                kept_masks=count,
                accepted=bool(p in valid),
                reasons=[
                    reason
                    for condition, reason in [
                        (count < config.min_views, "insufficient_views"),
                        (count / visible_per_prompt[p] < config.keep_thres, "insufficient_kept_fraction"),
                    ]
                    if condition
                ],
            )
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
    if evidence is not None:
        for p, support in zip(valid, supports, strict=True):
            evidence.emit(
                "voting",
                prompt=int(p),
                assigned_points=len(support),
                insufficient_observations=int(np.count_nonzero(seen[column[p]] < config.min_views)),
                above_vote_threshold=int(np.count_nonzero(score[column[p]] >= config.vote_thres)),
            )
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
                if evidence is not None:
                    evidence.emit(
                        "merge",
                        prompts=[int(valid[i]), int(valid[j])],
                        reason="support_overlap",
                        overlap=_jaccard(per_prompt[i], per_prompt[j]),
                        threshold=config.merge_thres,
                    )
    groups: dict[int, list[np.ndarray]] = {}
    for i, support in enumerate(supports):
        groups.setdefault(find(i), []).append(support)
    instances = []
    for group, parts in groups.items():
        members = np.unique(np.concatenate(parts))
        before_floor = len(members)
        members = members[above_floor_mask(points[members], floor_model)]
        cleaned = _largest_cluster(points, members, config)
        if evidence is not None:
            evidence.emit(
                "instance_decision",
                instance_key=hashlib.sha256(cleaned.astype("<i8").tobytes()).hexdigest(),
                prompts=[int(valid[i]) for i in range(len(valid)) if find(i) == group],
                before_floor=before_floor,
                floor_removed=before_floor - len(members),
                cluster_removed=len(members) - len(cleaned),
                retained=len(cleaned),
                accepted=len(cleaned) >= config.min_instance_points,
                reason=None if len(cleaned) >= config.min_instance_points else "too_few_instance_points",
            )
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


def _segment_multiview(
    proposal: Proposal,
    points: np.ndarray,
    floor_model: FloorModel,
    config: Sampro3dConfig,
    evidence: EvidenceRecorder | None,
) -> list[np.ndarray]:
    """Visibility-conditional voting and complete-link, co-view-consistent identity groups."""
    from dataclasses import asdict

    if not proposal.visible:
        raise ValueError("multiview refinement requires per-view visibility evidence")
    if evidence is not None:
        evidence.emit("config", thresholds=asdict(config), input_points=len(points))
    kept = _surviving_records(proposal, config, evidence)
    by_prompt: dict[int, dict[int, int]] = {}
    for record in kept:
        prompt, view = int(proposal.prompt[record]), int(proposal.view[record])
        previous = by_prompt.setdefault(prompt, {}).get(view)
        if previous is None or proposal.iou[record] > proposal.iou[previous]:
            by_prompt[prompt][view] = record
    valid = []
    for prompt in sorted(by_prompt):
        observations = len(np.unique(proposal.view[proposal.prompt == prompt]))
        retained = len(by_prompt[prompt])
        accepted = retained >= config.min_views and retained / observations >= config.keep_thres
        if evidence is not None:
            evidence.emit(
                "prompt_decision",
                prompt=prompt,
                observations=observations,
                kept_masks=retained,
                accepted=accepted,
                reasons=[] if accepted else ["insufficient_multiview_support"],
            )
        if accepted:
            valid.append(prompt)
    if not valid:
        return []
    hits = np.zeros((len(valid), len(points)), dtype=np.float32)
    seen = np.zeros_like(hits)
    for index, prompt in enumerate(valid):
        for view, record in by_prompt[prompt].items():
            seen[index, proposal.visible[view]] += 1
            hits[index, proposal.members[record]] += 1
    score = np.divide(hits, seen, out=np.zeros_like(hits), where=seen > 0)
    # An observed tie is not a positive majority. Occlusion adds no negative vote.
    support = score > config.vote_thres
    if evidence is not None:
        for index, prompt in enumerate(valid):
            evidence.emit(
                "voting",
                prompt=prompt,
                assigned_points=int(support[index].sum()),
                single_view_points=int((support[index] & (seen[index] == 1)).sum()),
                reason="visibility_conditional_strict_majority",
            )
    compatible = np.eye(len(valid), dtype=bool)
    for i, left in enumerate(valid):
        for j in range(i + 1, len(valid)):
            right = valid[j]
            overlap = _jaccard(np.flatnonzero(support[i]), np.flatnonzero(support[j]))
            if overlap < config.merge_thres:
                continue
            views = sorted(by_prompt[left].keys() & by_prompt[right].keys())
            agreements = [
                _jaccard(proposal.members[by_prompt[left][view]], proposal.members[by_prompt[right][view]])
                for view in views
            ]
            agree = len(views) >= config.min_views and all(value >= config.merge_thres for value in agreements)
            compatible[i, j] = compatible[j, i] = agree
            if evidence is not None:
                evidence.emit(
                    "merge_decision",
                    prompts=[left, right],
                    accepted=agree,
                    shared_views=len(views),
                    minimum_view_overlap=min(agreements, default=0.0),
                    reason="consistent_coview_support" if agree else "conflicting_or_missing_coview_support",
                )
    groups: list[list[int]] = []
    for index in range(len(valid)):
        target = next((group for group in groups if compatible[index, group].all()), None)
        if target is None:
            groups.append([index])
        else:
            target.append(index)
    group_scores = np.stack([score[group].max(axis=0) for group in groups])
    best = group_scores.max(axis=0)
    tied_best = group_scores == best
    # A broad bridge prompt must not erase a distinct, consistently supported object.
    # Resolve equal maxima using all tracks in each identity group; do not lower the vote threshold.
    agreement = np.stack([score[group].mean(axis=0) for group in groups])
    agreement[~tied_best] = -np.inf
    owners = agreement.argmax(axis=0)
    exclusive = (best > config.vote_thres) & ((agreement == agreement.max(axis=0)).sum(axis=0) == 1)
    if evidence is not None:
        ambiguous = (tied_best.sum(axis=0) > 1) & (best > config.vote_thres)
        evidence.emit(
            "ownership_resolution",
            tied_points=int(ambiguous.sum()),
            resolved_by_group_agreement=int((ambiguous & exclusive).sum()),
            unresolved=int((ambiguous & ~exclusive).sum()),
            reason="cross_prompt_group_agreement",
        )
    eligible = object_point_mask(points, floor_model)
    instances = []
    for owner, group in enumerate(groups):
        members = np.flatnonzero(exclusive & (owners == owner) & eligible)
        if len(members):
            pairs = cKDTree(points[members]).query_pairs(config.cluster_radius_m, output_type="ndarray")
            from scipy.sparse import coo_matrix

            graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(members), len(members)))
            count, components = connected_components(graph, directed=False)
            retained = []
            for component in range(count):
                part = members[components == component]
                # Components need repeated mask support, not just spatial proximity to a large body.
                views = {
                    view
                    for index in group
                    for view, record in by_prompt[valid[index]].items()
                    if np.intersect1d(part, proposal.members[record]).size
                }
                if len(part) >= config.min_mask_points and len(views) >= config.min_views:
                    retained.append(part)
            cleaned = np.sort(np.concatenate(retained)) if retained else members[:0]
        else:
            cleaned = members
        accepted = len(cleaned) >= config.min_instance_points
        if evidence is not None:
            evidence.emit(
                "instance_decision",
                instance_key=hashlib.sha256(cleaned.astype("<i8").tobytes()).hexdigest(),
                prompts=[valid[index] for index in group],
                retained=len(cleaned),
                cluster_removed=len(members) - len(cleaned),
                accepted=accepted,
                reason=None if accepted else "too_few_multiview_component_points",
            )
        if accepted:
            instances.append(cleaned)
    return sorted(instances, key=lambda members: (-len(members), int(members[0])))
