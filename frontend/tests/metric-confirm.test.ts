import { describe, expect, it } from "vitest";

import { metricInput, nextPointHint, parseDistance } from "@/features/studio/metric";
import { parseMetricPreview } from "@/lib/contracts/studio";

const POINTS = [
  [0, 0, 0],
  [1, 0, 0],
  [0, 0, -1],
  [1, 0, -1],
  [0, 1, -1],
] as const;

describe("metric confirmation input", () => {
  it("maps A, B then three floor points to the REC-06 payload", () => {
    expect(metricInput(POINTS, "2,5")).toEqual({
      point_a: [0, 0, 0],
      point_b: [1, 0, 0],
      floor_points: [
        [0, 0, -1],
        [1, 0, -1],
        [0, 1, -1],
      ],
      distance_m: 2.5,
    });
  });

  it("refuses incomplete points or invalid distances", () => {
    expect(metricInput(POINTS.slice(0, 4), "2")).toBeNull();
    for (const bad of ["", "0", "-1", "abc", "1e3", "2000"]) expect(parseDistance(bad)).toBeNull();
    expect(parseDistance(" 0.75 ")).toBe(0.75);
  });

  it("guides the next point", () => {
    expect(nextPointHint(0)).toMatch(/điểm A/);
    expect(nextPointHint(2)).toMatch(/sàn 1\/3/);
    expect(nextPointHint(5)).toBeNull();
  });

  it("rejects malformed previews", () => {
    const preview = {
      preview_checksum: "sha256:x",
      scale_m_per_sfm_unit: 4,
      floor_residual_m: 0,
      measured_distance_m: 2,
      camera_height_min_m: 1,
      camera_height_max_m: 1.5,
      warnings: [],
    };
    expect(parseMetricPreview(preview).scale_m_per_sfm_unit).toBe(4);
    expect(() => parseMetricPreview({ ...preview, scale_m_per_sfm_unit: null })).toThrow();
    expect(() => parseMetricPreview({ ...preview, warnings: [1] })).toThrow();
  });
});
