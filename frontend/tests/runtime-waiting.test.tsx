import { describe, expect, it } from "vitest";
import { progressSceneStatus } from "@/features/studio/sceneStatus";
import { parseJobProgress, type JobProgress } from "@/lib/contracts/studio";

describe("runtime waiting state (T-040)", () => {
  const queued: JobProgress = {
    job_id: "job-1", status: "QUEUED", current_stage: "ST-INPUT-VALIDATE", attempt: 1,
    started_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", completed_at: null,
    preview_ready: false, error: null, waiting_for: "runtime", stages: [],
  };

  it("is accepted by the progress parser", () => {
    expect(parseJobProgress(queued).waiting_for).toBe("runtime");
    expect(() => parseJobProgress({ ...queued, waiting_for: "something_else" })).toThrow();
  });

  it("shows the waiting-for-GPU label, distinct from waiting for resources", () => {
    expect(progressSceneStatus(queued)).toMatchObject({ label: "Đang chờ GPU", active: true, group: "running" });
    expect(progressSceneStatus({ ...queued, waiting_for: "resources" }).label).toBe("Đang chờ tài nguyên");
  });
});
