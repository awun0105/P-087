"""Annotated synthetic 3D supports, not real SAM2 predictions or scene ground truth."""

from dataclasses import dataclass

import numpy as np

from src.services.scene.floor_model import fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.sampro3d.consolidate import Proposal


@dataclass(frozen=True)
class SegmentationCase:
    name: str
    points: np.ndarray
    truth: np.ndarray
    proposal: Proposal


def cases() -> list[SegmentationCase]:
    floor = np.array([(x, y, 0.0) for x in np.arange(-1, 2, 0.1) for y in np.arange(-1, 1, 0.1)])

    def block(x: float, z: float = 0.3) -> np.ndarray:
        return np.array([(x + i * 0.04, j * 0.04, z + k * 0.04) for i in range(6) for j in range(5) for k in range(2)])

    points = np.vstack([floor, block(0), block(0.5)])
    a, b = np.arange(len(floor), len(floor) + 60), np.arange(len(floor) + 60, len(points))
    truth = np.full(len(points), -1, dtype=np.int32)
    truth[a], truth[b] = 0, 1
    result = []

    def add(name: str, records: list, visibility: list | None = None, xyz: np.ndarray = points) -> None:
        result.append(
            SegmentationCase(
                name,
                xyz.copy(),
                truth.copy(),
                Proposal(
                    view=np.array([r[0] for r in records]),
                    prompt=np.array([r[1] for r in records]),
                    iou=np.array([r[2] for r in records]),
                    members=[np.asarray(r[3]) for r in records],
                    visible=visibility
                    if visibility is not None
                    else [np.arange(len(points))] * (1 + max(r[0] for r in records)),
                ),
            )
        )

    stable_b = [(v, int(b[0]), 0.95, b) for v in range(3)]
    add("prompt_switch", [(v, int(a[p]), 0.99 if v == p else 0.9, a) for v in range(3) for p in range(3)] + stable_b)
    # The appendage is observed once; occluded views are not negative observations.
    core, tip = a[:40], a[40:]
    add(
        "occluded_part",
        [(v, int(a[0]), 0.95, a if v == 0 else core) for v in range(3)] + stable_b,
        [np.arange(len(points)), np.setdiff1d(np.arange(len(points)), tip), np.setdiff1d(np.arange(len(points)), tip)],
    )
    separated = points.copy()
    separated[a[40:], 2] += 0.4
    add("disconnected_part", [(v, int(a[0]), 0.95, a) for v in range(3)] + stable_b, xyz=separated)
    # One undersegmented view must not merge two separately observed objects.
    nearby = points.copy()
    nearby[b, 0] -= 0.22
    add(
        "nearby_fused_view",
        [(v, int(owner[0]), 0.95, np.r_[a, b] if v < 2 else owner) for v in range(4) for owner in (a, b)],
        xyz=nearby,
    )
    add(
        "complementary_prompts",
        [(v, int(a[0]), 0.95, a[:45]) for v in range(3)] + [(v, int(a[-1]), 0.94, a[15:]) for v in range(3)] + stable_b,
    )
    low = points.copy()
    low[a, 2] = np.where(np.arange(60) % 2, 0.003, 0.04)
    add("near_floor", [(v, int(a[0]), 0.95, np.r_[a, np.arange(10)]) for v in range(3)] + stable_b, xyz=low)
    return result


def floor_model(case: SegmentationCase):
    points = case.points[case.truth < 0]
    return fit_canonical_floor_model(points, point_cloud_checksum(points))
