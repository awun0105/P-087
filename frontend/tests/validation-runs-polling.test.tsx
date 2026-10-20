import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ValidationRunsPanel } from "@/features/studio/ValidationRunsPanel";

const CANDIDATE = `sha256:${"a".repeat(64)}`;
const running = {
  schema_version: "1.0", job_id: "job-a", run_id: "validation-run-1", attempt: 1, scene_revision: "rev-004",
  candidate_checksum: CANDIDATE, validation_config_checksum: `sha256:${"b".repeat(64)}`, run_status: "RUNNING", status: "RUNNING",
  requested_at: "2026-10-09T10:00:00Z", started_at: "2026-10-09T10:00:01Z", completed_at: null, report_checksum: null,
  selected: false, retryable: false, error_code: null,
};
const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }) as Response;

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
}

afterEach(() => { vi.useRealTimers(); setVisibility("visible"); });

describe("validation run polling (T-063)", () => {
  it("does not ask again while the tab is hidden and catches up when it is shown", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    global.fetch = vi.fn().mockImplementation(async () => reply([running]));
    render(<ValidationRunsPanel jobId="job-a" sceneRevision="rev-004" candidateChecksum={CANDIDATE} canMutateJob={false} />);
    await screen.findAllByText(/Đang chạy|RUNNING/);
    expect(global.fetch).toHaveBeenCalledTimes(1);

    setVisibility("hidden");
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(global.fetch).toHaveBeenCalledTimes(1);

    setVisibility("visible");
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await vi.advanceTimersByTimeAsync(10); });
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });
});
