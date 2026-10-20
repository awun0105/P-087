import { describe, expect, it } from "vitest";

import { sceneSummaryStatus } from "@/features/studio/sceneStatus";
import type { SceneSummary } from "@/lib/contracts/studio";

function summary(next_action: SceneSummary["next_action"], status = "SUCCEEDED"): SceneSummary {
  return {
    project: { project_id: "p", name: "Kho", source_type: "upload", privacy: {} as never, input_video: null, created_at: null },
    latest_job: { job_id: "job-1", status, current_stage: "ST-OBJECT-EXTRACT", stage_artifacts: [] } as never,
    preview_ready: true,
    next_action,
  } as SceneSummary;
}

describe("scene list labels from the backend next action (T-062)", () => {
  it("uses the same wording as the scene page", () => {
    expect(sceneSummaryStatus(summary("review_objects")).label).toBe("Chờ duyệt vật");
    expect(sceneSummaryStatus(summary("confirm_metric", "RUNNING")).label).toBe("Cần xác nhận tỉ lệ");
    expect(sceneSummaryStatus(summary("scene_ready")).label).toBe("Đã dựng scene");
    expect(sceneSummaryStatus(summary("wait_system", "QUEUED")).label).toBe("Đang chờ worker");
  });
  it("falls back to the old flags when an older API sends no next action", () => {
    expect(sceneSummaryStatus(summary(undefined)).label).toBe("Đã dựng scene");
  });
});
