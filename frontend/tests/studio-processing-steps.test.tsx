/** T-073: các bước xếp lịch của job (CPU / GPU / chờ bạn) trên màn tiến trình. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProcessingSteps, stepStatusText } from "@/features/studio/scene/ProcessingSteps";
import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import { isJobStale } from "@/features/studio/scene/state";
import { parseJobProgress, type JobProgress, type JobStepView } from "@/lib/contracts/studio";

vi.mock("@/features/studio/scene/AttemptHistory", () => ({ AttemptHistory: () => <div /> }));

const steps: JobStepView[] = [
  { step_id: "prepare", kind: "cpu", state: "done", waiting_on: null, attempt: 1, started_at: "2026-10-21T00:00:00Z", finished_at: "2026-10-21T00:03:12Z" },
  { step_id: "pose_visual", kind: "gpu", state: "ready", waiting_on: "gpu", attempt: 1, started_at: null, finished_at: null },
  { step_id: "metric_confirm", kind: "user", state: "pending", waiting_on: null, attempt: 1, started_at: null, finished_at: null },
];

const waiting: JobProgress = {
  job_id: "job-steps", status: "RUNNING", current_stage: "ST-FRAME-EXTRACT", attempt: 1,
  started_at: "2026-10-21T00:00:00Z", updated_at: "2026-10-21T00:03:12Z", completed_at: null,
  preview_ready: false, error: null, stages: [], steps,
  queue: { position: 1, waiting: 1, running: 1, workers: 1, estimated_wait_seconds: null, estimate_samples: 0 },
};

describe("bước xếp lịch của job", () => {
  it("nói đúng bước nào đang chờ GPU, bước nào đã xong và mất bao lâu", () => {
    render(<ProcessingSteps steps={steps} now={Date.parse("2026-10-21T00:05:00Z")} />);
    const list = screen.getByRole("list", { name: "Các bước xử lý" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("CPU");
    expect(rows[0]).toHaveTextContent("Chuẩn bị video");
    expect(rows[0]).toHaveTextContent("Xong · 3 phút 12 giây");
    expect(rows[1]).toHaveTextContent("GPU");
    expect(rows[1]).toHaveTextContent("Đang chờ GPU trống");
    expect(rows[2]).toHaveTextContent("Bạn");
    expect(rows[2]).toHaveTextContent("Chưa tới");
  });

  it("có câu riêng cho bước chờ CPU, đang chạy và chờ bạn", () => {
    expect(stepStatusText({ ...steps[0], state: "ready", waiting_on: "cpu" })).toBe("Đang chờ CPU trống");
    expect(stepStatusText({ ...steps[0], state: "running" })).toBe("Đang chạy");
    expect(stepStatusText({ ...steps[2], state: "waiting_user", waiting_on: "user" })).toBe("Chờ bạn");
  });

  it("hiện trong màn tiến trình và job dừng giữa hai bước không bị coi là mất kết nối", () => {
    render(<ProgressTab jobId={waiting.job_id} progress={waiting} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByTestId("processing-steps")).toHaveTextContent("Đang chờ GPU trống");
    expect(isJobStale(waiting, Date.parse("2026-10-21T01:00:00Z"))).toBe(false);
    expect(isJobStale({ ...waiting, queue: null, steps: [] }, Date.parse("2026-10-21T01:00:00Z"))).toBe(true);
  });

  it("đọc bước từ API, bỏ dòng lạ và chấp nhận server cũ không gửi bước", () => {
    const parsed = parseJobProgress({ ...waiting, steps: [...steps, { step_id: "future_step", kind: "tpu", state: "done" }] });
    expect(parsed.steps?.map((step) => step.step_id)).toEqual(["prepare", "pose_visual", "metric_confirm"]);
    const older: Partial<JobProgress> = { ...waiting };
    delete older.steps;
    expect(parseJobProgress(older).steps).toBeUndefined();
  });
});
