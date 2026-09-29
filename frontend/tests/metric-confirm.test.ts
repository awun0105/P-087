import { describe, expect, it } from "vitest";

import { metricInput, nextPointHint, parseDistance, segments } from "@/features/studio/metric";
import { parseLidarMeasurements, parseMetricPreview } from "@/lib/contracts/studio";

const POINTS = [
  [0, 0, 0],
  [1, 0, 0],
  [0, 1, 0],
  [0, 2, 0],
  [0, 0, -1],
  [1, 0, -1],
  [0, 1, -1],
] as const;

describe("metric confirmation input", () => {
  it("maps A, B, C, D then three floor points to the REC-06 payload", () => {
    expect(metricInput(POINTS, "2,5", "1.2")).toEqual({
      point_a: [0, 0, 0],
      point_b: [1, 0, 0],
      distance_m: 2.5,
      check_a: [0, 1, 0],
      check_b: [0, 2, 0],
      check_distance_m: 1.2,
      floor_points: [
        [0, 0, -1],
        [1, 0, -1],
        [0, 1, -1],
      ],
      distance_source: "user_measured",
    });
    expect(metricInput(POINTS, "2.345678901", "1.5", "lidar_demo")?.distance_source).toBe("lidar_demo");
  });

  it("refuses incomplete points or invalid distances", () => {
    expect(metricInput(POINTS.slice(0, 6), "2", "1")).toBeNull();
    expect(metricInput(POINTS, "2", "")).toBeNull();
    for (const bad of ["", "0", "-1", "abc", "1e3", "2000"]) expect(parseDistance(bad)).toBeNull();
    expect(parseDistance(" 0.75 ")).toBe(0.75);
  });

  it("exposes A/B and C/D segments once four points exist", () => {
    expect(segments(POINTS.slice(0, 3))).toBeNull();
    expect(segments(POINTS)).toEqual([
      [
        [0, 0, 0],
        [1, 0, 0],
      ],
      [
        [0, 1, 0],
        [0, 2, 0],
      ],
    ]);
  });

  it("guides the next point", () => {
    expect(nextPointHint(0)).toMatch(/điểm A/);
    expect(nextPointHint(2)).toMatch(/điểm C/);
    expect(nextPointHint(4)).toMatch(/sàn 1\/3/);
    expect(nextPointHint(7)).toBeNull();
  });

  it("rejects malformed previews and LiDAR measurements", () => {
    const preview = {
      preview_checksum: "sha256:x",
      scale_m_per_sfm_unit: 4,
      floor_residual_m: 0,
      measured_distance_m: 2,
      camera_height_min_m: 1,
      camera_height_max_m: 1.5,
      distance_source: "user_measured",
      check_measured_m: 1,
      check_error_m: 0,
      check_tolerance_m: 0.04,
      check_passed: true,
      warnings: [],
    };
    expect(parseMetricPreview(preview).scale_m_per_sfm_unit).toBe(4);
    expect(() => parseMetricPreview({ ...preview, check_passed: "yes" })).toThrow();
    expect(() => parseMetricPreview({ ...preview, distance_source: "guess" })).toThrow();
    const distance = { clicked_world: [], lidar_points_m: [], snap_offsets_m: [0.01, 0.02], distance_m: 2 };
    expect(parseLidarMeasurements({ anchor: distance, check: distance }).anchor.distance_m).toBe(2);
    expect(() => parseLidarMeasurements({ anchor: { ...distance, distance_m: 0 }, check: distance })).toThrow();
  });
});
