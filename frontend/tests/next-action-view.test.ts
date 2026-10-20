import { describe, expect, it } from "vitest";

import { nextActionView, operationLabel } from "@/features/studio/nextAction";
import type { NextActionKind } from "@/lib/contracts/pipeline";

const KINDS: NextActionKind[] = [
  "wait_system", "review_anonymization", "confirm_metric", "retry_job", "job_failed", "job_cancelled", "retry_geometry",
  "review_objects", "choose_object_method", "confirm_objects", "scene_ready", "released", "await_review", "review_package",
  "fix_preflight", "create_package",
];

const ctx = { wait: null, waitingFor: null, objectifyMode: null, phase: null, currentStepShort: null, isReviewer: false, gpu: null, now: 0 };

describe("one table of next-action wording (T-062)", () => {
  it("has a title, a description and a status for every kind", () => {
    for (const kind of KINDS) {
      const view = nextActionView({ kind, step_id: null, owner: kind === "wait_system" ? "system" : "user", pending_count: null }, ctx);
      expect(view.title, kind).toBeTruthy();
      expect(view.status.label, kind).toBeTruthy();
    }
  });
  it("says 'Đang dựng lại vùng' for a region rebuild everywhere", () => {
    const view = nextActionView(
      { kind: "wait_system", step_id: "ST-SCENE-DECOMPOSE", owner: "system", pending_count: null },
      { ...ctx, wait: { kind: "scene_operation", step_id: "ST-SCENE-DECOMPOSE", since: null }, objectifyMode: "region" },
    );
    expect(view.title).toBe("Đang dựng lại vùng");
    expect(view.status.label).toBe("Đang dựng lại vùng");
    expect(operationLabel("geometry")).toBe("Đang tạo mesh");
  });
  it("never calls the metric wait 'collision'", () => {
    const view = nextActionView({ kind: "confirm_metric", step_id: "ST-METRIC-CANONICALIZE", owner: "user", pending_count: null }, ctx);
    expect(view.status.label).not.toMatch(/collision/i);
    expect(view.target).toEqual({ tab: "studio", mode: "metric" });
  });
  it("counts objects to review in the description", () => {
    const view = nextActionView({ kind: "review_objects", step_id: "ST-OBJECT-CONFIRM", owner: "user", pending_count: 3 }, ctx);
    expect(view.description).toContain("3 vật chờ xác nhận");
  });
  it("says the GPU machine is starting while a job waits for it", () => {
    const gpu = { state: "starting", since: "2026-10-20T08:00:00Z", expected_startup_seconds: 900 } as never;
    const view = nextActionView(
      { kind: "wait_system", step_id: null, owner: "system", pending_count: null },
      { ...ctx, waitingFor: "resources", gpu, now: Date.parse("2026-10-20T08:05:00Z") },
    );
    expect(view.title).toBe("Đang khởi động máy GPU");
    expect(view.description).toContain("10 phút");
  });
});
