/** ReviewPanel: duyệt cần chấp nhận từng cảnh báo + xác nhận; từ chối cần lý do; gửi đúng checksum. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewPanel } from "@/features/studio/ReviewPanel";
import type { Me } from "@/lib/api/auth";

const auth = vi.hoisted(() => ({ me: { auth_required: false, user: null } as Me }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => auth }));

const CANDIDATE = "sha256:" + "c".repeat(64);
const REPORT = "sha256:" + "d".repeat(64);

function state(status: string, extra: Record<string, unknown> = {}) {
  return {
    record: { scene_revision: "rev-004", status, candidate_checksum: CANDIDATE, validation_report_checksum: REPORT },
    validation: {
      overall_result: "PASS",
      validator_version: "fixture-0",
      checks: [
        { check_id: "scene_load", result: "PASS", message: null },
        { check_id: "penetration_minor", result: "FAIL", message: "2 cm" },
      ],
      path_results: [{ pair_id: "pair-1", result: "CLEAR", message: null }],
    },
    warning_ids: ["penetration_minor"],
    approval: null,
    release: null,
    release_archive: null,
    blockers: [],
    ...extra,
  };
}

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

describe("ReviewPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
    auth.me = { auth_required: false, user: null };
  });

  it("phê duyệt chỉ sau khi chấp nhận cảnh báo và xác nhận, gửi đúng checksum", async () => {
    vi.mocked(global.fetch)
      .mockResolvedValueOnce(reply(state("READY_FOR_REVIEW")))
      .mockResolvedValueOnce(
        reply(state("RELEASED", {
          approval: { reviewer_id: "u-rev", decision: "APPROVE", reason: null, decided_at: "2026-09-30T10:00:00Z" },
          release: { release_timestamp: "2026-09-30T10:00:01Z", release_manifest_checksum: "sha256:" + "e".repeat(64) },
          release_archive: { artifact_uri: "artifact://x/release.zip" },
        })),
      );
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    const approve = await screen.findByRole("button", { name: "Phê duyệt để phát hành" });
    expect(approve).toBeDisabled();
    fireEvent.click(screen.getByLabelText("penetration_minor"));
    fireEvent.click(approve);
    fireEvent.click(screen.getByRole("button", { name: /Xác nhận phê duyệt/ }));
    expect(await screen.findByText(/Tải bản phát hành/)).toBeInTheDocument();
    const [url, init] = vi.mocked(global.fetch).mock.calls[1]!;
    expect(String(url)).toContain("/api/v1/jobs/job-a/review-decision");
    expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({
      decision: "APPROVE",
      candidate_checksum: CANDIDATE,
      validation_report_checksum: REPORT,
      accepted_warning_ids: ["penetration_minor"],
    });
  });

  it("từ chối cần lý do; chưa có báo cáo thì chỉ hiện lý do chặn", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(state("READY_FOR_REVIEW")));
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    const reject = await screen.findByRole("button", { name: "Yêu cầu sửa" });
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Lý do yêu cầu sửa"), { target: { value: "Kệ lệch" } });
    await waitFor(() => expect(reject).toBeEnabled());
  });

  it("chưa có validation: chặng Isaac chưa khả dụng, không có nút duyệt", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply({ ...state("CANDIDATE_READY"), validation: null, warning_ids: [], blockers: ["Chưa có báo cáo validation Isaac"] }),
    );
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    // Q2: validation Isaac chưa có runtime → báo "Chưa khả dụng", không giả như đang chờ.
    expect(await screen.findByText(/Chưa khả dụng: cần máy RTX/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Phê duyệt để phát hành" })).toBeNull();
    expect(screen.getByText("Có gói cho revision này")).toBeInTheDocument();
  });

  it("Editor chỉ đọc báo cáo; không thấy action duyệt hoặc từ chối", async () => {
    auth.me = { auth_required: true, user: { user_id: "editor-1", email: "editor@example.com", display_name: "Editor", role: "editor", active: true, daily_job_quota: 10 } };
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(state("READY_FOR_REVIEW")));
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    expect(await screen.findByText(/Chỉ Reviewer có quyền/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Phê duyệt để phát hành" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Yêu cầu sửa" })).toBeNull();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("không cho quyết định trên trạng thái của revision cũ", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(state("READY_FOR_REVIEW")));
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-005" />);
    expect(await screen.findByText(/Trạng thái duyệt đang thuộc rev-004/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Phê duyệt để phát hành" })).toBeNull();
  });

  it("lỗi đọc trạng thái duyệt có đường thử lại", async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new Error("Mất kết nối")).mockResolvedValueOnce(reply(state("READY_FOR_REVIEW")));
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Không kết nối được máy chủ");
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByRole("button", { name: "Phê duyệt để phát hành" })).toBeInTheDocument();
  });
});
