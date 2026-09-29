/**
 * Test cho ReviewLifecyclePanel (PRODUCT-10).
 *
 * Bản cŽ dùng `decision: "PENDING"` — một giá trị **backend không thể phát ra**
 * (`ApprovalDecision` chỉ có APPROVE/REJECT). Vì vậy ba test "cover" Approve/Reject
 * thật ra cover một trạng thái không tồn tại, và UI viết theo đó nên nút Approve/
 * Reject **không bao giờ hiện** với response thật.
 *
 * Nay `approval` vắng mặt là "chưa có quyết định" và đó là lúc form phải hiện.
 *
 * Panel mặc định chỉ đọc (`enabled=false`) cho tới khi backend có authorization và
 * lưu quyết định review thật; các ca thao tác bật `enabled` tường minh.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewLifecyclePanel } from "@/features/review/ReviewLifecycle";
import type { ApprovalRecord, ReviewState } from "@/lib/contracts/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

const APPROVAL: ApprovalRecord = {
  schema_version: "1.0",
  candidate_checksum: `sha256:${"a".repeat(63)}1`,
  validation_report_checksum: `sha256:${"b".repeat(63)}2`,
  reviewer_id: "reviewer-mock-001",
  decision: "REJECT",
  reason: "sai vị trí pallet",
  decided_at: "2026-09-26T12:00:00Z",
  accepted_warning_ids: [],
  record_checksum: `sha256:${"c".repeat(63)}3`,
};

const PENDING_REVIEW: ReviewState = {
  job_id: "job-fixture-001",
  synthetic_authorization: true,
  note: "mock",
};

const DECIDED_REVIEW: ReviewState = { ...PENDING_REVIEW, approval: APPROVAL };

function mockOk() {
  vi.mocked(global.fetch).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as Response);
}

describe("ReviewLifecyclePanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("mặc định chỉ đọc: nút bị khóa và không gửi request", () => {
    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={PENDING_REVIEW} />);
    const approve = screen.getByRole("button", { name: /Approve/ });
    expect(approve).toBeDisabled();
    expect(screen.getByText("Review chỉ đọc")).toBeInTheDocument();
    fireEvent.click(approve);
    expect(vi.mocked(global.fetch)).not.toHaveBeenCalled();
  });

  it("chưa có approval thì form Approve/Reject phải hiện", () => {
    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={PENDING_REVIEW} enabled />);
    expect(screen.getByRole("button", { name: /Approve/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Reject/ })).toBeDisabled();
  });

  it("đã có approval thì không cho quyết lần hai", () => {
    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={DECIDED_REVIEW} />);
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Reject/ })).toBeNull();
    expect(screen.getByText("REJECT")).toBeInTheDocument();
  });

  it("gửi approve với checksum từ candidate thật", async () => {
    mockOk();
    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={PENDING_REVIEW} enabled />);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    await waitFor(() => {
      const [url, init] = vi.mocked(global.fetch).mock.calls[0]!;
      expect(url).toContain("/api/v1/jobs/job-fixture-001/review/approve");
      const body = JSON.parse((init as RequestInit).body as string);
      // Chưa có approval thì không có checksum để gửi; payload phải null chứ không
      // được bịa giá trị.
      expect(body.candidate_checksum).toBeNull();
      expect(body.validation_report_checksum).toBeNull();
    });
  });

  it("gửi reject kèm lý do, và chặn reject khi lý do trống", async () => {
    mockOk();
    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={PENDING_REVIEW} enabled />);
    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    await waitFor(() => expect(vi.mocked(global.fetch)).not.toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Lý do review"), { target: { value: "sai vị trí pallet" } });
    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    await waitFor(() => {
      const [, init] = vi.mocked(global.fetch).mock.calls[0]!;
      expect(JSON.parse((init as RequestInit).body as string).reason).toBe("sai vị trí pallet");
    });
  });

  it("cờ synthetic_authorization phải hiện vì approval từ fixture không phải uỷ quyền thật", () => {
    render(<ReviewLifecyclePanel jobId="job-fixture-001" review={DECIDED_REVIEW} />);
    expect(screen.getByTestId("synthetic-authorization")).toBeInTheDocument();
  });
});
