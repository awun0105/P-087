import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PipelineContext } from "@/features/studio/scene/pipelineContext";
import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import type { PipelineView } from "@/lib/contracts/pipeline";
import type { JobProgress } from "@/lib/contracts/studio";

vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => ({ me: { auth_required: false, user: null }, refresh: vi.fn() }) }));

const progress: JobProgress = {
  job_id: "job-1", status: "QUEUED", current_stage: "ST-INPUT-VALIDATE", attempt: 1, started_at: "2026-10-20T08:00:00Z",
  updated_at: "2026-10-20T08:00:00Z", completed_at: null, stages: [], preview_ready: false, waiting_for: null, error: null,
};

function view(state: "starting" | "ready"): PipelineView {
  return {
    job_id: "job-1", scene_revision: null, usable: false, steps: [], current_step: null, version: "v",
    wait: { kind: "queue", step_id: null, since: null }, next_action: { kind: "wait_system", step_id: null, owner: "system", pending_count: null },
    progress, objectify: null,
    gpu: { state, since: "2026-10-20T08:00:00Z", elapsed_seconds: null, expected_startup_seconds: 900, remaining_seconds: null, sample_count: 0 } as PipelineView["gpu"],
  };
}

function renderTab(state: "starting" | "ready") {
  return render(
    <PipelineContext.Provider value={view(state)}>
      <ProgressTab jobId="job-1" progress={progress} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />
    </PipelineContext.Provider>,
  );
}

describe("GPU startup notice on the progress tab", () => {
  it("shows GPU startup notice while the GPU machine is starting", () => {
    renderTab("starting");
    expect(screen.getByText("Đang khởi động máy GPU")).toBeInTheDocument();
  });
  it("no GPU notice once the GPU is ready", () => {
    renderTab("ready");
    expect(screen.queryByText("Đang khởi động máy GPU")).toBeNull();
  });
});
