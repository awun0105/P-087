/**
 * Test cho ReviewLifecyclePanel (PRODUCT-10).
 *
 * Mock fetch để kiểm tra approve/reject payload và validation client-side.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewLifecyclePanel } from "@/features/review/ReviewLifecycle";
import type { ReviewState } from "@/lib/contracts/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

const FIXTURE_REVIEW: ReviewState = {
  job_id: "job-fixture-001",
  approval: {
    schema_version: "1.0",
    candidate_checksum: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1",
    validation_report_checksum: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb2",
    reviewer_id: "reviewer-mock-001",
    decision: "PENDING",
    reason: null,
    decided_at: "2026-09-26T12:00:00Z",
    accepted_warning_ids: [],
    record_checksum: "sha256:ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc3",
  },
  synthetic_authorization: true,
  note: "mock",
};

describe("ReviewLifecyclePanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("disable reject khi chưa nhập lý do", () => {
    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={FIXTURE_REVIEW} />);
    expect(screen.getByRole("button", { name: /Reject/ })).toBeDisabled();
  });

  it("gửi approve với candidate/validation checksum", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={FIXTURE_REVIEW} />);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    await waitFor(() => {
      const [url, init] = vi.mocked(global.fetch).mock.calls[0]!;
      expect(url).toContain("/api/v1/jobs/job-fixture-001/review/approve");
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.candidate_checksum).toBe(FIXTURE_REVIEW.approval.candidate_checksum);
      expect(body.validation_report_checksum).toBe(FIXTURE_REVIEW.approval.validation_report_checksum);
    });
  });

  it("gửi reject với lý do", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={FIXTURE_REVIEW} />);
    fireEvent.change(screen.getByLabelText("Lý do review"), { target: { value: "sai vị trí pallet" } });
    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));

    await waitFor(() => {
      const [, init] = vi.mocked(global.fetch).mock.calls[0]!;
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.reason).toBe("sai vị trí pallet");
    });
  });
});
