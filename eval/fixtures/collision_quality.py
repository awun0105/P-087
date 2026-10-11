"""Small deterministic geometry fixtures for collision-quality regressions."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ClearanceFixture:
    fixture_id: str
    vertices_m: tuple[tuple[float, float, float], ...]
    expected_blocked: bool


ROBOT_RADIUS_M = 0.461
ROBOT_HEIGHT_M = 0.308
SAMPLE_RETENTION_TOLERANCE_M = 0.001
PATH_CENTER_M = (0.0, 0.0, 0.0)

CLEARANCE_FIXTURES = (
    ClearanceFixture("known_clear_path", (), False),
    ClearanceFixture("shelf_leg_thin_obstacle", ((0.20, 0.0, 0.10),), True),
    ClearanceFixture("pallet_foot_low_obstacle", ((0.35, 0.0, 0.05),), True),
    ClearanceFixture("cable_low_obstacle", ((0.25, 0.0, 0.04),), True),
    ClearanceFixture("wall_crossing_path", ((0.10, 0.0, 0.20),), True),
    ClearanceFixture("ramp_edge_crossing_path", ((0.12, 0.0, 0.18),), True),
    ClearanceFixture("low_box_crossing_path", ((0.05, 0.0, 0.12),), True),
    ClearanceFixture("narrow_passage_inside_envelope", ((0.45, 0.0, 0.12),), True),
    ClearanceFixture("wide_passage_outside_envelope", ((0.50, 0.0, 0.12),), False),
)

FLOOR_SUPPORT_SAMPLES_M = np.asarray(
    ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0), (0.5, 0.5, 0.0)),
    dtype=float,
)

CAMERA_OFFSET_SENSITIVITY = {
    "obstacle_vertex_m": (0.48, 0.0, 0.12),
    "camera_center_m": (0.0, 0.0, 0.0),
    "robot_center_after_offset_m": (0.05, 0.0, 0.0),
    "offset_xy_m": (0.05, 0.0),
    "camera_path_expected_blocked": False,
    "robot_path_expected_blocked": True,
}
