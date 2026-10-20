import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NextAction } from "@/features/studio/scene/NextAction";
import { PipelineContext } from "@/features/studio/scene/pipelineContext";
import { getJobScene, getReviewState, getSimulationPackage } from "@/lib/api/studio";
import type { PipelineView } from "@/lib/contracts/pipeline";
import type { JobProgress } from "@/lib/contracts/studio";

vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => ({ me: { auth_required: false, user: null }, refresh: vi.fn() }) }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getJobScene: vi.fn(), getSimulationPackage: vi.fn(), getReviewState: vi.fn(), getObjectifyState: vi.fn().mockResolvedValue({ status: "idle" }),
}));

const progress: JobProgress = {
  job_id: "job-1", status: "SUCCEEDED", current_stage: "ST-OBJECT-EXTRACT", attempt: 1, started_at: "2026-10-20T08:00:00Z",
  updated_at: "2026-10-20T08:00:00Z", completed_at: "2026-10-20T09:00:00Z", stages: [], preview_ready: true, waiting_for: null, error: null,
  capabilities: { can_mutate: true, can_cancel: false, can_retry: false },
};

function view(): PipelineView {
  return {
    job_id: "job-1", scene_revision: "rev-002", usable: false, steps: [], current_step: "ST-OBJECT-CONFIRM", wait: null, version: "v",
    next_action: { kind: "review_objects", step_id: "ST-OBJECT-CONFIRM", owner: "user", pending_count: 4 },
    progress, objectify: null, gpu: null,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("bell inside the scene page (T-062)", () => {
  it("uses the pipeline next action and makes no scene, package or review request", async () => {
    render(
      <PipelineContext.Provider value={view()}>
        <NextAction jobId="job-1" progress={progress} current="progress" mode="scene" sceneReady revision="rev-002" busy={false} onOpen={vi.fn()} onRetry={vi.fn()} variant="popover" />
      </PipelineContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Thông báo của scene" }));
    expect(await screen.findByText("Duyệt vật rồi Tạo mesh")).toBeInTheDocument();
    expect(screen.getByText(/4 vật chờ xác nhận/)).toBeInTheDocument();
    expect(getJobScene).not.toHaveBeenCalled();
    expect(getSimulationPackage).not.toHaveBeenCalled();
    expect(getReviewState).not.toHaveBeenCalled();
  });
});
