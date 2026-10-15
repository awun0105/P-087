"""Exclusive ownership metrics with one-to-one object matching; no candidate-count proxy."""

import numpy as np
from scipy.optimize import linear_sum_assignment


def ownership_metrics(truth: np.ndarray, predicted: np.ndarray) -> dict:
    if truth.ndim != 1 or predicted.shape != truth.shape:
        raise ValueError("expected aligned, exclusive ownership labels")
    actual = np.unique(truth[truth >= 0])
    found = np.unique(predicted[predicted >= 0])
    overlap = np.array(
        [[np.count_nonzero((truth == a) & (predicted == p)) for p in found] for a in actual], dtype=int
    ).reshape(len(actual), len(found))
    sizes = np.array([np.count_nonzero(truth == a) for a in actual])
    predicted_sizes = np.array([np.count_nonzero(predicted == p) for p in found])
    union = sizes[:, None] + predicted_sizes[None, :] - overlap
    iou = np.divide(overlap, union, out=np.zeros_like(overlap, dtype=float), where=union > 0)
    rows, cols = linear_sum_assignment(-iou)
    recall = np.zeros(len(actual))
    purity = np.zeros(len(found))
    recall[rows] = overlap[rows, cols] / sizes[rows]
    purity[cols] = overlap[rows, cols] / predicted_sizes[cols]
    return dict(
        completeness=float(recall.mean()) if len(recall) else 1.0,
        purity=float(purity.mean()) if len(purity) else 0.0,
        split_errors=int(np.maximum((overlap > 0).sum(axis=1) - 1, 0).sum()),
        merge_errors=int(np.maximum((overlap > 0).sum(axis=0) - 1, 0).sum()),
        background_leakage=int(np.count_nonzero((truth < 0) & (predicted >= 0))),
        object_to_background=int(np.count_nonzero((truth >= 0) & (predicted < 0))),
    )


def instance_labels(instances: list[np.ndarray], count: int) -> np.ndarray:
    labels = np.full(count, -1, dtype=np.int32)
    for owner, members in enumerate(instances):
        if np.any(labels[members] != -1):
            raise ValueError("instances have overlapping ownership")
        labels[members] = owner
    return labels


def benchmark() -> dict:
    """Replay fixed annotated supports; never invoke SAM2, a renderer or a scene mutation."""
    import hashlib
    from dataclasses import asdict

    from eval.fixtures.segmentation import cases, floor_model
    from src.services.scene.sampro3d.consolidate import Sampro3dConfig, segment

    results = []
    for case in cases():
        model = floor_model(case)
        checksum = hashlib.sha256()
        for array in (
            case.points,
            case.truth,
            case.proposal.view,
            case.proposal.prompt,
            case.proposal.iou,
            *case.proposal.members,
            *case.proposal.visible,
        ):
            checksum.update(str((array.shape, array.dtype)).encode())
            checksum.update(array.tobytes())
        result = dict(case=case.name, known_limit=case.known_limit, input_checksum="sha256:" + checksum.hexdigest())
        for name, mode in (("before", "legacy"), ("after", "multiview_v1")):
            config = Sampro3dConfig(refinement=mode)
            prediction = instance_labels(segment(case.proposal, case.points, model, config), len(case.points))
            metrics = ownership_metrics(case.truth, prediction)
            near = (case.truth >= 0) & (case.points[:, 2] > 0) & (case.points[:, 2] <= model.floor_band_m)
            if near.any():
                metrics["near_floor_completeness"] = ownership_metrics(case.truth[near], prediction[near])[
                    "completeness"
                ]
            result[name] = dict(config=asdict(config), metrics=metrics)
        results.append(result)
    return dict(
        source="annotated_synthetic", stage="multiview_consolidation", real_scene_acceptance=False, cases=results
    )


def main() -> None:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(benchmark(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(report)
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
