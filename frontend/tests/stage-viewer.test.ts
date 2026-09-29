import { describe, expect, it } from "vitest";

import { topDownAxes } from "@/features/studio/StageViewer";
import { parseStageViews, type StageView } from "@/lib/contracts/studio";

const camera = (center: [number, number, number]) => ({ frame_id: 0, center, rotation_xyzw: [0, 0, 0, 1] as [number, number, number, number] });

describe("stage viewer", () => {
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
  });
});
