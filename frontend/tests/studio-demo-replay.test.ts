import { describe, expect, it } from "vitest";

import { replayPlan, replayState } from "@/features/studio/useDemoReplay";
import type { DemoStage } from "@/lib/contracts/studio";

const ids = ["ST-INPUT-VALIDATE", "ST-PRIVACY-GATE", "ST-FRAME-EXTRACT", "ST-CAMERA-POSE", "ST-VISUAL-RECON"] as const;

function stages(durations: (number | null)[]): DemoStage[] {
  return ids.map((stage_id, index) => ({ stage_id, duration_seconds: durations[index], summary: "" }));
}

describe("demo replay", () => {
  it("chia đều khi bundle không có thời lượng thật", () => {
    const plan = replayPlan(stages([null, null, null, null, null]));
    expect(new Set(plan.filter((length) => length > 0)).size).toBe(1);
    expect(plan).toHaveLength(8);
    expect(plan.slice(5)).toEqual([0, 0, 0]);
  });

  it("theo tỉ lệ thời lượng thật và giữ thời gian tối thiểu mỗi stage", () => {
    const plan = replayPlan(stages([5, 1, 30, 300, 900]));
    expect(plan[4]).toBeGreaterThan(plan[3]);
    expect(Math.min(...plan.filter((length) => length > 0))).toBeGreaterThanOrEqual(1400);
  });

  it("stage trước xong, stage hiện tại chạy với tỉ lệ, stage sau chờ", () => {
    const input = stages([10, 10, 10, 10, 10]);
    const plan = replayPlan(input);
    const views = replayState(input, plan, plan[0] + plan[1] / 2);
    expect(views.map((view) => view.state)).toEqual(["succeeded", "running", "pending", "pending", "pending", "pending", "pending", "pending"]);
    expect(views[1].fraction).toBeCloseTo(0.5);
    expect(views[0].seconds).toBe(10);
    const done = replayState(input, plan, plan.reduce((a, b) => a + b, 0));
    expect(done.slice(0, 5).every((view) => view.state === "succeeded")).toBe(true);
    expect(done.slice(5).every((view) => view.state === "pending")).toBe(true);
  });
  it("bundle cũ thiếu bước hoặc có bước lỗi không được tạo success khi bỏ qua", () => {
    const input: DemoStage[] = [{ stage_id: "ST-VISUAL-RECON", duration_seconds: 10, summary: "" },
      { stage_id: "ST-OBJECT-EXTRACT", state: "failed", duration_seconds: null, summary: "" }];
    const plan = replayPlan(input);
    const done = replayState(input, plan, plan.reduce((a, b) => a + b, 0));
    expect(done).toHaveLength(8);
    expect(done.filter((view) => view.state === "succeeded").map((view) => view.stage_id)).toEqual(["ST-VISUAL-RECON"]);
    expect(done[7].state).toBe("failed");
    expect(done[0].state).toBe("pending");
  });
  it("bundle mới replay được cả geometry và object đã có evidence", () => {
    const input: DemoStage[] = [...stages([1, 1, 1, 1, 1]),
      { stage_id: "ST-METRIC-CANONICALIZE", state: "succeeded", duration_seconds: null, summary: "" },
      { stage_id: "ST-RGB-GEOMETRY", state: "succeeded", duration_seconds: 12, summary: "" },
      { stage_id: "ST-OBJECT-EXTRACT", state: "succeeded", duration_seconds: 20, summary: "" }];
    const plan = replayPlan(input);
    expect(replayState(input, plan, plan.reduce((a, b) => a + b, 0)).every((view) => view.state === "succeeded")).toBe(true);
  });
});
