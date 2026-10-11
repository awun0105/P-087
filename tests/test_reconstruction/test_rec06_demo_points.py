"""ADR 0004 §6: tự chọn 7 điểm demo trên sàn LiDAR phía trước camera, đổi ngược về SfM."""

import math

import numpy as np
import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.reconstruction.alignment.similarity import fit_similarity
from src.services.reconstruction.rgb.canonical.lidar_assist import (
    DemoLidarSupport,
    LidarAssist,
    LidarAssistContext,
    demo_points,
)

REF = ProductArtifactRef(
    artifact_type="X",
    schema_version="1.0",
    artifact_uri="artifact://jobs/job-1/x.json",
    artifact_checksum="sha256:" + "0" * 64,
    data_class="derived",
    producer_stage="ST-RGB-LIDAR-ALIGN",
    job_id="job-1",
)


def _context(floor_extent: float = 8.0) -> LidarAssistContext:
    # SfM → world: scale 2, tịnh tiến sàn về z=0 (SfM z=-0.2 là sàn).
    source = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    fit = fit_similarity(source, [(2 * x, 2 * y, 2 * z + 0.4) for x, y, z in source])
    grid = np.arange(-floor_extent, floor_extent, 0.04)
    xs, ys = np.meshgrid(grid, grid)
    floor = np.stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)], axis=1)
    support = DemoLidarSupport(
        job_id="job-1",
        camera_poses_checksum="sha256:x",
        alignment_ref=REF,
        lidar_geometry_ref=REF,
        lidar_metadata_ref=REF,
    )
    return LidarAssistContext(support, "sha256:x", fit, floor)


CAMERAS = [(0.1 * i, 0.0, 0.0) for i in range(30)]  # đi theo +X, cao 0,4 m trên sàn


def test_points_lie_on_floor_ahead_and_segments_meet_rules() -> None:
    context = _context()
    points = demo_points(context, CAMERAS)
    world = [context.fit.apply(point) for point in points]
    assert all(abs(point[2]) < 1e-6 for point in world)  # đúng mặt sàn LiDAR
    assert all(point[0] > 1.0 for point in world)  # phía trước camera gốc
    anchor = LidarAssist.measure(context, points[0], points[1])
    check = LidarAssist.measure(context, points[2], points[3])
    assert anchor.distance_m == pytest.approx(2.0, abs=0.06) and check.distance_m == pytest.approx(1.5, abs=0.06)
    assert anchor.point_sources == ("lidar_surface", "lidar_surface")
    floor = world[4:]
    area = abs(np.cross(np.subtract(floor[1], floor[0]), np.subtract(floor[2], floor[0]))[2]) / 2
    assert area > 0.5 and math.dist(world[0], world[2]) > 0.5


def test_refuses_when_lidar_does_not_cover_floor() -> None:
    with pytest.raises(ValueError, match="không phủ đủ"):
        demo_points(_context(floor_extent=0.5), CAMERAS)
    with pytest.raises(ValueError, match="đứng yên"):
        demo_points(_context(), [(0.0, 0.0, 0.0)] * 12)
