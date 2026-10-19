import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ValidationRunsPanel } from "@/features/studio/ValidationRunsPanel";
import type { ValidationRunView } from "@/lib/contracts/api";

const CANDIDATE = `sha256:${"a".repeat(64)}`;

function run(overrides: Partial<ValidationRunView> = {}): ValidationRunView {
  return {
    schema_version: "1.0",
    job_id: "job-a",
    run_id: "validation-run-1",
    attempt: 1,
    scene_revision: "rev-004",
    candidate_checksum: CANDIDATE,
    validation_config_checksum: `sha256:${"b".repeat(64)}`,
    run_status: "COMPLETED",
    status: "COMPLETED",
    requested_at: "2026-10-09T10:00:00Z",
    started_at: "2026-10-09T10:00:01Z",
    completed_at: "2026-10-09T10:00:10Z",
    report_checksum: `sha256:${"c".repeat(64)}`,
    selected: false,
    retryable: false,
    error_code: null,
    ...overrides,
  };
}

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

describe("ValidationRunsPanel", () => {
  it("submits an idempotent run for the current candidate and refreshes its status", async () => {
    const queued = run({ run_status: "QUEUED", status: "QUEUED", started_at: null, completed_at: null, report_checksum: null });
    global.fetch = vi.fn()
      .mockResolvedValueOnce(reply([]))
      .mockResolvedValueOnce(reply(queued, 202))
      .mockResolvedValueOnce(reply([queued]));
    render(<ValidationRunsPanel jobId="job-a" sceneRevision="rev-004" candidateChecksum={CANDIDATE} canMutateJob />);

    fireEvent.click(await screen.findByRole("button", { name: "Chạy validation" }));

    expect(await screen.findByText("Đang chờ worker")).toBeInTheDocument();
    const [, request] = vi.mocked(global.fetch).mock.calls[1]!;
    expect(request?.method).toBe("POST");
    expect(request?.headers).toMatchObject({ "Idempotency-Key": expect.any(String) });
    expect(JSON.parse(String(request?.body))).toEqual({ candidate_checksum: CANDIDATE });
  });

  it("cancels an active run and displays the persisted cancellation", async () => {
    const active = run({ run_status: "RUNNING", status: "RUNNING", completed_at: null, report_checksum: null });
    const cancelled = { ...active, run_status: "CANCELLED" as const, status: "CANCELLED" as const, completed_at: "2026-10-09T10:00:12Z" };
    global.fetch = vi.fn()
      .mockResolvedValueOnce(reply([active]))
      .mockResolvedValueOnce(reply(cancelled))
      .mockResolvedValueOnce(reply([cancelled]));
    render(<ValidationRunsPanel jobId="job-a" sceneRevision="rev-004" candidateChecksum={CANDIDATE} canMutateJob />);

    fireEvent.click(await screen.findByRole("button", { name: "Hủy run" }));

    expect(await screen.findByText("Đã hủy")).toBeInTheDocument();
    expect(vi.mocked(global.fetch).mock.calls[1]?.[0]).toContain("/cancel");
  });

  it("retries only a retryable failure", async () => {
    const failed = run({ run_status: "FAILED", status: "FAILED", retryable: true, error_code: "ISAAC_RUNTIME_TIMEOUT" });
    const queued = { ...failed, run_id: "validation-run-2", attempt: 2, run_status: "QUEUED" as const, status: "QUEUED" as const, retryable: false, error_code: null, completed_at: null, report_checksum: null };
    global.fetch = vi.fn()
      .mockResolvedValueOnce(reply([failed]))
      .mockResolvedValueOnce(reply(queued, 202))
      .mockResolvedValueOnce(reply([queued, failed]));
    render(<ValidationRunsPanel jobId="job-a" sceneRevision="rev-004" candidateChecksum={CANDIDATE} canMutateJob />);

    fireEvent.click(await screen.findByRole("button", { name: "Thử lại" }));

    expect(await screen.findByText("Đang chờ worker")).toBeInTheDocument();
    expect(vi.mocked(global.fetch).mock.calls[1]?.[0]).toContain("/retry");
    expect(vi.mocked(global.fetch).mock.calls[1]?.[1]?.headers).toMatchObject({ "Idempotency-Key": expect.any(String) });
  });

  it("selects a completed report with the candidate and current selection CAS", async () => {
    const completed = run();
    const selected = { ...completed, selected: true };
    const onSelected = vi.fn();
    global.fetch = vi.fn()
      .mockResolvedValueOnce(reply([completed]))
      .mockResolvedValueOnce(reply(selected))
      .mockResolvedValueOnce(reply([selected]));
    render(<ValidationRunsPanel jobId="job-a" sceneRevision="rev-004" candidateChecksum={CANDIDATE} canMutateJob onSelected={onSelected} />);

    expect(await screen.findByRole("link", { name: "Tải Execution log" })).toHaveAttribute(
      "href",
      "/api/v1/jobs/job-a/validation-runs/validation-run-1/artifacts/execution.log",
    );
    fireEvent.click(screen.getByRole("button", { name: "Dùng report này cho review" }));

    expect(await screen.findByText("Đang được dùng")).toBeInTheDocument();
    expect(onSelected).toHaveBeenCalledTimes(1);
    const [, request] = vi.mocked(global.fetch).mock.calls[1]!;
    expect(request?.method).toBe("POST");
    expect(JSON.parse(String(request?.body))).toEqual({ candidate_checksum: CANDIDATE, expected_selected_run_id: null });
  });

  it("uses the current candidate selection as the CAS value across policy updates", async () => {
    const oldPolicy = run({ selected: true });
    const currentPolicy = run({ run_id: "validation-run-current-policy", validation_config_checksum: `sha256:${"d".repeat(64)}` });
    const selected = { ...currentPolicy, selected: true };
    const replacedOldPolicy = { ...oldPolicy, selected: false };
    global.fetch = vi.fn()
      .mockResolvedValueOnce(reply([currentPolicy, oldPolicy]))
      .mockResolvedValueOnce(reply(selected))
      .mockResolvedValueOnce(reply([selected, replacedOldPolicy]));
    render(<ValidationRunsPanel jobId="job-a" sceneRevision="rev-004" candidateChecksum={CANDIDATE} canMutateJob />);

    fireEvent.click(await screen.findByRole("button", { name: "Dùng report này cho review" }));

    await waitFor(() => expect(screen.getAllByText("Đang được dùng")).toHaveLength(1));
    const [, request] = vi.mocked(global.fetch).mock.calls[1]!;
    expect(JSON.parse(String(request?.body))).toEqual({
      candidate_checksum: CANDIDATE,
      expected_selected_run_id: oldPolicy.run_id,
    });
  });

  it("shows history without mutation controls when the user cannot edit this job", async () => {
    global.fetch = vi.fn().mockResolvedValueOnce(reply([run()]));
    render(<ValidationRunsPanel jobId="job-a" sceneRevision="rev-004" candidateChecksum={CANDIDATE} canMutateJob={false} />);

    expect(await screen.findByText("Hoàn tất")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Chạy validation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dùng report này cho review" })).toBeNull();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
  });
});
