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
