import { describe, expect, it } from "vitest";

import { topDownAxes } from "@/features/studio/StageViewer";
import { parseModeComparison, parseStageViews, type StageView } from "@/lib/contracts/studio";

const camera = (center: [number, number, number]) => ({ frame_id: 0, center, rotation_xyzw: [0, 0, 0, 1] as [number, number, number, number] });

describe("stage viewer", () => {
  it("chỉ nhận quaternion hiển thị hữu hạn, đủ bốn phần tử và có độ dài một", () => {
    const view = { stage_id: "x", kind: "gaussian", title: "t", note: "", unit: "arbitrary", refs: [], cameras: [] };
    for (const rotation of [undefined, null, [0, 0, 0, 1]]) {
      expect(parseStageViews({ views: [{ ...view, display_rotation_xyzw: rotation }] })).toHaveLength(1);
    }
    for (const rotation of [[0, 0, 1], [0, 0, 0, 0], [0, 0, 0, 2], [0, 0, Number.NaN, 1], [0, 0, Infinity, 1]]) {
      expect(() => parseStageViews({ views: [{ ...view, display_rotation_xyzw: rotation }] })).toThrow();
    }
  });

  it("uses x/y in meters and the two widest axes for arbitrary SfM units", () => {
    const base: StageView = { stage_id: "ST-CAMERA-POSE", kind: "cameras", title: "", note: "", unit: "meter", refs: [], cameras: [] };
    expect(topDownAxes(base)).toEqual([0, 1]);
    const sfm = { ...base, unit: "arbitrary" as const, cameras: [camera([0, 0, 0]), camera([5, 0.1, 9])] };
    expect(topDownAxes(sfm)).toEqual([0, 2]); // trục y gần như không đổi: là trục "lên"
  });

  it("rejects unknown kinds and malformed cameras", () => {
    const view = { stage_id: "x", kind: "mesh", title: "t", note: "", unit: "meter", refs: [{ artifact_uri: "a", artifact_checksum: "b", artifact_type: "c" }], cameras: [] };
    expect(parseStageViews({ job_id: "j", views: [view] })).toHaveLength(1);
    expect(() => parseStageViews({ job_id: "j", views: [{ ...view, kind: "video" }] })).toThrow();
    expect(() => parseStageViews({ job_id: "j", views: [{ ...view, cameras: [{ center: [0, Number.NaN, 0] }] }] })).toThrow();
    // Trường thử lại COLMAP (T-071): tuỳ chọn, nhưng có thì phải đúng kiểu.
    expect(parseStageViews({ job_id: "j", views: [{ ...view, retry_count: 2, registration_warning: true, registered_ratio: 0.4 }] })).toHaveLength(1);
    for (const patch of [{ retry_count: -1 }, { retry_count: 1.5 }, { registration_warning: "yes" }, { registered_ratio: Number.NaN }]) {
      expect(() => parseStageViews({ job_id: "j", views: [{ ...view, ...patch }] })).toThrow();
    }
  });
});


describe("mode comparison contract", () => {
  const mode = (status: string, scale: number | null) => ({
    mode: "lidar", title: "t", status, note: "", steps: [], scale_m_per_sfm_unit: scale,
    camera_height_mean_m: null, camera_height_range_m: null,
  });
  it("never accepts a number on a mock or missing column", () => {
    const ok = { job_id: "j", modes: [mode("mock", null), mode("missing", null), mode("measured", 1.2)], difference: null, lidar_ground_truth_assisted: true };
    expect(parseModeComparison(ok).modes).toHaveLength(3);
    expect(() => parseModeComparison({ ...ok, modes: [mode("mock", 1.1), mode("missing", null), mode("measured", 1.2)] })).toThrow();
    expect(() => parseModeComparison({ ...ok, modes: [mode("mock", null), mode("missing", null), mode("measured", null)] })).toThrow();
  });
  it("accepts real estimated and confirmed scales with uncertainty, and rejects invalid evidence", () => {
    const ok = { job_id: "j", modes: [{ ...mode("estimated", 3.0441), relative_uncertainty: 0.0526, frames_used: 60 }, mode("confirmed", 3.0441), mode("missing", null)], difference: null, lidar_ground_truth_assisted: false };
    expect(parseModeComparison(ok).modes[0].status).toBe("estimated");
    for (const patch of [{ scale_m_per_sfm_unit: null }, { scale_m_per_sfm_unit: 0 }, { scale_m_per_sfm_unit: Number.NaN }, { relative_uncertainty: -0.1 }, { relative_uncertainty: Number.POSITIVE_INFINITY }, { frames_used: 0 }]) {
      expect(() => parseModeComparison({ ...ok, modes: [{ ...ok.modes[0], ...patch }, ...ok.modes.slice(1)] })).toThrow();
    }
  });

});
