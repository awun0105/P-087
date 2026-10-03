import { describe, expect, it } from "vitest";

import { estimatedDistances, metricInput, nextPointHint, parseDistance, proposalPoints, segments } from "@/features/studio/metric";
import { parseDemoSelection, parseLidarMeasurements, parseMetricPreview, parseMetricProposal, type MetricProposal } from "@/lib/contracts/studio";

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

  it("accepts only a full 7-point demo selection", () => {
    const distance = {
      clicked_world: [],
      lidar_points_m: [],
      snap_offsets_m: [0, 0],
      point_sources: ["lidar_surface", "lidar_surface"],
      distance_m: 2,
    };
    const measurements = { anchor: distance, check: distance };
    const points = Array.from({ length: 7 }, (_, index) => [index, 0, 0]);
    expect(parseDemoSelection({ points, measurements }).points).toHaveLength(7);
    expect(() => parseDemoSelection({ points: points.slice(0, 6), measurements })).toThrow();
    expect(() => parseDemoSelection({ points: [...points.slice(0, 6), [0, Number.NaN, 0]], measurements })).toThrow();
  });
});

describe("đề xuất tỉ lệ tự động (ADR 0001 §2)", () => {
  const proposal: MetricProposal = {
    status: "ESTIMATED", job_id: "job-a", scale_m_per_sfm_unit: 1.2, frame_dispersion: 0.38, relative_uncertainty: 0.07,
    frames_used: 50, pairs_used: 20000,
    floor: { points: [[0, 0, 0], [4, 0, 0], [0, 3, 0]], residual_m: 0.02, support_points: 300 },
    segments: { point_a: [0, 0, 0], point_b: [4, 0, 0], distance_m: 4.8, check_a: [0, 0, 0], check_b: [0, 3, 0], check_distance_m: 3.6 },
  };

  it("xếp bảy điểm đúng thứ tự A, B, C, D, sàn 1–3", () => {
    expect(proposalPoints(proposal)).toEqual([[0, 0, 0], [4, 0, 0], [0, 0, 0], [0, 3, 0], [0, 0, 0], [4, 0, 0], [0, 3, 0]]);
    expect(proposalPoints({ ...proposal, floor: null })).toBeNull(); // chỉ có tỉ lệ: người dùng tự chọn điểm
    expect(proposalPoints({ ...proposal, segments: null })).toBeNull();
  });

  it("khoảng cách ước lượng = độ dài trong scene × tỉ lệ, tính lại theo điểm đang chọn", () => {
    expect(estimatedDistances([[[0, 0, 0], [4, 0, 0]], [[0, 0, 0], [0, 3, 0]]], 1.2)).toEqual([4.8, 3.5999999999999996]);
    const [ab, cd] = estimatedDistances([[[1, 2, 3], [4, 6, 3]], [[0, 0, 0], [0, 0, 2]]], 0.5);
    expect(ab).toBeCloseTo(2.5);
    expect(cd).toBeCloseTo(1);
    // Số gửi lên backend đi qua chuỗi rồi parse lại phải giữ nguyên giá trị (backend so khớp tới 1e-6).
    const input = metricInput([[1, 2, 3], [4, 6, 3], [0, 0, 0], [0, 0, 2], [0, 0, 0], [1, 0, 0], [0, 1, 0]], String(ab), String(cd), "ai_estimated");
    expect(input?.distance_m).toBe(ab);
    expect(input?.check_distance_m).toBe(cd);
    expect(input?.distance_source).toBe("ai_estimated");
  });

  it("từ chối đề xuất hỏng thay vì điền số lạ vào bước xác nhận", () => {
    expect(parseMetricProposal(proposal).scale_m_per_sfm_unit).toBe(1.2);
    expect(parseMetricProposal({ ...proposal, floor: null, segments: null }).floor).toBeNull();
    for (const broken of [
      { ...proposal, status: "CONFIRMED" },
      { ...proposal, scale_m_per_sfm_unit: 0 },
      { ...proposal, scale_m_per_sfm_unit: Number.NaN },
      { ...proposal, relative_uncertainty: -1 },
      { ...proposal, floor: { ...proposal.floor, points: [[0, 0, 0]] } },
      { ...proposal, segments: { ...proposal.segments, distance_m: -2 } },
      { ...proposal, segments: { ...proposal.segments, point_a: [0, "x", 0] } },
      null,
    ]) {
      expect(() => parseMetricProposal(broken)).toThrow();
    }
  });

  it("bản xem trước nhận nguồn ai_estimated", () => {
    const preview = {
      preview_checksum: "sha256:x", scale_m_per_sfm_unit: 1.2, floor_residual_m: 0, measured_distance_m: 4.8,
      camera_height_min_m: 0.3, camera_height_max_m: 0.4, distance_source: "ai_estimated", check_measured_m: 3.6,
      check_error_m: 0, check_tolerance_m: 0.05, check_passed: true, warnings: ["Khoảng cách là ước lượng tự động"],
    };
    expect(parseMetricPreview(preview).distance_source).toBe("ai_estimated");
    expect(() => parseMetricPreview({ ...preview, distance_source: "guessed" })).toThrow();
  });
});
