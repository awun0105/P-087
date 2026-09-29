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
    expect(new Set(plan).size).toBe(1);
  });

  it("theo tỉ lệ thời lượng thật và giữ thời gian tối thiểu mỗi stage", () => {
    const plan = replayPlan(stages([5, 1, 30, 300, 900]));
    expect(plan[4]).toBeGreaterThan(plan[3]);
    expect(Math.min(...plan)).toBeGreaterThanOrEqual(1400);
  });

  it("stage trước xong, stage hiện tại chạy với tỉ lệ, stage sau chờ", () => {
    const input = stages([10, 10, 10, 10, 10]);
    const plan = replayPlan(input);
    const views = replayState(input, plan, plan[0] + plan[1] / 2);
    expect(views.map((view) => view.state)).toEqual(["succeeded", "running", "pending", "pending", "pending"]);
    expect(views[1].fraction).toBeCloseTo(0.5);
    expect(views[0].seconds).toBe(10);
    const done = replayState(input, plan, plan.reduce((a, b) => a + b, 0));
    expect(done.every((view) => view.state === "succeeded")).toBe(true);
  });
});
