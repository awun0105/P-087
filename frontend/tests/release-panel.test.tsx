/**
 * Test cho ReleasePanel (PRODUCT-11).
 *
 * Mock fetch để kiểm tra payload release và validation client-side.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReleasePanel } from "@/features/review/ReleasePanel";
import type { ApprovalRecord } from "@/lib/contracts/api";

const FIXTURE_APPROVAL: ApprovalRecord = {
  schema_version: "1.0",
  candidate_checksum: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1",
  validation_report_checksum: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb2",
  reviewer_id: "reviewer-001",
  decision: "APPROVE",
  reason: null,
  decided_at: "2026-09-26T12:00:00Z",
  accepted_warning_ids: [],
  record_checksum: "sha256:ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc3",
};

describe("ReleasePanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("không cho release khi job chưa SUCCEEDED", () => {
    render(
      <ReleasePanel
        jobId="job-fixture-001"
        approved
        checksumMatch
        approvalRecord={FIXTURE_APPROVAL}
        jobStatus="RUNNING"
      />,
    );
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("gửi release payload khi đủ điều kiện", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        release_id: "rel-job-fixture-001",
        release_checksum: "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        released_at: "2026-09-26T20:00:00Z",
      }),
    } as Response);

    render(
      <ReleasePanel
        jobId="job-fixture-001"
        approved
        checksumMatch
        approvalRecord={FIXTURE_APPROVAL}
        jobStatus="SUCCEEDED"
      />,
    );

    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      const [url, init] = vi.mocked(global.fetch).mock.calls[0]!;
      expect(url).toContain("/api/v1/jobs/job-fixture-001/release");
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.approval_record_checksum).toBe(FIXTURE_APPROVAL.record_checksum);
      expect(body.candidate_checksum).toBe(FIXTURE_APPROVAL.candidate_checksum);
      expect(body.validation_report_checksum).toBe(FIXTURE_APPROVAL.validation_report_checksum);
    });

    expect(await screen.findByText(/Release thành công!/)).toBeInTheDocument();
  });
});
