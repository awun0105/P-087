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
      candidate_checksum: CANDIDATE,
      report_checksum: REPORT,
      environment_versions: { isaac_sim: "fixture-0" },
      checks: [
        { check_id: "scene_load", result: "PASS", message: null, evidence_refs: [] },
      ],
      path_results: [{ pair_id: "pair-1", result: "BLOCKED", message: "Lối đi có vật cản tùy chọn.", evidence_refs: [] }],
    },
    isaac_runtime_proof: true,
    warning_ids: ["path:pair-1"],
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

  it("hiển thị trạng thái tải trong khi API chưa trả review state", async () => {
    let resolveResponse!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    });
    vi.mocked(global.fetch).mockReturnValueOnce(pending);
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);

    expect(screen.getByRole("status")).toHaveTextContent("Đang đọc trạng thái duyệt");
    resolveResponse(reply(state("READY_FOR_REVIEW")));
    expect(await screen.findByRole("button", { name: "Phê duyệt để phát hành" })).toBeInTheDocument();
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
    fireEvent.click(screen.getByLabelText("path:pair-1"));
    fireEvent.click(approve);
    fireEvent.click(screen.getByRole("button", { name: /Xác nhận phê duyệt/ }));
    expect(await screen.findByText(/Tải bản phát hành/)).toBeInTheDocument();
    const [url, init] = vi.mocked(global.fetch).mock.calls[1]!;
    expect(String(url)).toContain("/api/v1/jobs/job-a/review-decision");
    expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({
      decision: "APPROVE",
      candidate_checksum: CANDIDATE,
      validation_report_checksum: REPORT,
      accepted_warning_ids: ["path:pair-1"],
    });
  });

  it("từ chối cần lý do khi validation đã đủ điều kiện", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(state("READY_FOR_REVIEW")));
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    const reject = await screen.findByRole("button", { name: "Yêu cầu sửa" });
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Lý do yêu cầu sửa"), { target: { value: "Kệ lệch" } });
    await waitFor(() => expect(reject).toBeEnabled());
  });

  it("chưa có validation: blocker hiển thị dù không có report và không có action", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply({ ...state("CANDIDATE_READY"), validation: null, warning_ids: [], blockers: ["Chưa có báo cáo validation Isaac"] }),
    );
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    expect(await screen.findByText("Chưa đủ điều kiện duyệt")).toBeInTheDocument();
    expect(screen.getByText("Chưa có báo cáo validation Isaac")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Phê duyệt để phát hành" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Yêu cầu sửa" })).toBeNull();
    expect(screen.getByText("Có gói cho revision này")).toBeInTheDocument();
  });

  it("fail closed nếu API trả READY_FOR_REVIEW nhưng report không có trusted proof", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply(state("READY_FOR_REVIEW", { isaac_runtime_proof: false, blockers: ["Legacy report không được tin cậy"] })),
    );
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    expect(await screen.findByText("Legacy report không được tin cậy")).toBeInTheDocument();
    expect(screen.getByText(/chỉ dùng để xem thông tin/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Phê duyệt để phát hành" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Yêu cầu sửa" })).toBeNull();
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

  it("optional path warning hiện message/evidence để Reviewer chấp nhận; không nhầm với failed check", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(state("READY_FOR_REVIEW")));
    const onState = vi.fn();
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" onState={onState} />);
    const checkbox = await screen.findByLabelText("path:pair-1");
    expect(checkbox).toHaveAccessibleDescription("Lối đi có vật cản tùy chọn. · không kèm bằng chứng");
    expect(screen.queryByText(/chưa gắn với validation run worker/)).toBeNull();
    // Màn cha nhận đúng trạng thái đã chuẩn hoá để vẽ thẻ báo cáo.
    await waitFor(() => expect(onState).toHaveBeenLastCalledWith(expect.objectContaining({ isaac_runtime_proof: true, warning_ids: ["path:pair-1"] })));
  });

  it("đã quyết định thì hiện nguồn kết quả: checksum gói, báo cáo và bản ghi duyệt", async () => {
    const record = "sha256:" + "a".repeat(64);
    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply(state("APPROVED", {
        approval: { reviewer_id: "u-rev", decision: "APPROVE", reason: null, decided_at: "2026-09-30T10:00:00Z", candidate_checksum: CANDIDATE, validation_report_checksum: REPORT, record_checksum: record, accepted_warning_ids: ["path:pair-1"] },
      })),
    );
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    expect(await screen.findByText("Nguồn kết quả của quyết định")).toBeInTheDocument();
    expect(screen.getByText(record)).toBeInTheDocument();
    expect(screen.getByText(CANDIDATE)).toBeInTheDocument();
  });

  it("hiện lỗi seal an toàn và cho Reviewer thử lại dù release đang ở APPROVED", async () => {
    auth.me = {
      auth_required: true,
      user: { user_id: "u-rev", email: "reviewer@example.com", display_name: "Reviewer", role: "reviewer", active: true, daily_job_quota: 10 },
    };
    vi.mocked(global.fetch)
      .mockResolvedValueOnce(
        reply(state("APPROVED", {
          approval: { reviewer_id: "u-rev", decision: "APPROVE", reason: null, decided_at: "2026-09-30T10:00:00Z", candidate_checksum: CANDIDATE, validation_report_checksum: REPORT, record_checksum: "sha256:" + "a".repeat(64), accepted_warning_ids: ["path:pair-1"] },
          release_seal_error: "Bản phát hành chưa hoàn tất hoặc chưa vượt qua kiểm tra toàn vẹn; Reviewer có thể thử lại.",
          blockers: ["Release archive chưa vượt qua kiểm tra toàn vẹn"],
        })),
      )
      .mockResolvedValueOnce(reply(state("RELEASED", {
        approval: { reviewer_id: "u-rev", decision: "APPROVE", reason: null, decided_at: "2026-09-30T10:00:00Z", candidate_checksum: CANDIDATE, validation_report_checksum: REPORT, record_checksum: "sha256:" + "a".repeat(64), accepted_warning_ids: ["path:pair-1"] },
        release: { release_timestamp: "2026-09-30T10:00:01Z", release_manifest_checksum: "sha256:" + "e".repeat(64) },
        release_archive: { artifact_uri: "artifact://x/release.zip" },
      })));

    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);

    expect(await screen.findByText(/Bản phát hành chưa hoàn tất/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại phát hành" }));
    expect(await screen.findByText(/Tải bản phát hành/)).toBeInTheDocument();
    expect(String(vi.mocked(global.fetch).mock.calls[1]?.[0])).toContain("/api/v1/jobs/job-a/release-seal");
  });

  it("lỗi đọc trạng thái duyệt có đường thử lại", async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new Error("Mất kết nối")).mockResolvedValueOnce(reply(state("READY_FOR_REVIEW")));
    render(<ReviewPanel jobId="job-a" sceneRevision="rev-004" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Không kết nối được máy chủ");
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByRole("button", { name: "Phê duyệt để phát hành" })).toBeInTheDocument();
  });
});
