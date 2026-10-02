/** Bảng đánh giá: hiện đúng số và kết luận; bước chưa đo không bị vẽ như có kết quả; dữ liệu sai dạng thành lỗi. */

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EvaluationCard, StageMetrics } from "@/features/studio/evaluation/EvaluationCard";
import { parseJobEvaluation } from "@/lib/api/studio";

const EVALUATION = {
  job_id: "job-1", project_id: "project-1", scene_name: "Kho A", job_status: "SUCCEEDED", scene_revision: "rev-002",
  generated_at: "2026-10-02T03:00:00Z", schema_version: "1.0",
  groups: [
    {
      group_id: "ST-CAMERA-POSE", title: "Vị trí camera", status: "measured", note: null,
      metrics: [
        { key: "pose.registered_ratio", label: "Ảnh COLMAP dựng được vị trí", value: 96, unit: "%", display: "96.0 % (48/50)", meaning: "Phần ảnh có vị trí camera.", source: "self_check", verdict: "ok", threshold: "≥ 50%" },
        { key: "pose.error", label: "Sai số reprojection", value: 0.56, unit: "px", display: "0.56 px", meaning: "Lệch pixel.", source: "self_check", verdict: null, threshold: null },
      ],
    },
    {
      group_id: "ST-VISUAL-RECON", title: "Scene 3DGS", status: "measured", note: null,
      metrics: [{ key: "visual.novel_view_quality", label: "PSNR / SSIM / LPIPS", value: null, unit: null, display: "Chưa đo — cần lượt đánh giá riêng", meaning: "Góc nhìn mới.", source: "self_check", verdict: null, threshold: null }],
    },
    { group_id: "ST-RGB-GEOMETRY", title: "Hình học và va chạm", status: "pending", note: "Bước này chưa có kết quả.", metrics: [] },
  ],
};

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

describe("EvaluationCard", () => {
  beforeEach(() => { vi.unstubAllGlobals(); });

  it("hiện từng nhóm với giá trị, kết luận có ngưỡng, và ghi rõ bước chưa có kết quả", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(EVALUATION)));
    render(<EvaluationCard jobId="job-1" revision="rev-002" />);
    const ratio = (await screen.findByText("Ảnh COLMAP dựng được vị trí")).closest("div")!.parentElement!;
    expect(within(ratio).getByText("96.0 % (48/50)")).toBeInTheDocument();
    expect(within(ratio).getByText("Đạt")).toBeInTheDocument();
    expect(within(ratio).getByText(/Ngưỡng: ≥ 50%/)).toBeInTheDocument();
    expect(screen.getByText("0.56 px")).toBeInTheDocument();
    expect(screen.getAllByText("Đạt")).toHaveLength(1);
    expect(screen.getByText("Chưa đo — cần lượt đánh giá riêng")).toBeInTheDocument();
    expect(screen.getByText(/Chưa có kết quả\. Bước này chưa có kết quả\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Báo cáo \(\.md\)/ })).toHaveAttribute("href", "/api/v1/jobs/job-1/evaluation/report.md");
  });

  it("lỗi tải hiện thông báo, không hiện bảng trống như kết quả", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ detail: "Không tìm thấy job" }, 404)));
    render(<EvaluationCard jobId="job-x" revision="rev-001" />);
    expect(await screen.findByText(/Không tải được bảng đánh giá/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Báo cáo/ })).toBeNull();
  });
});

describe("StageMetrics", () => {
  beforeEach(() => { vi.unstubAllGlobals(); });

  it("chỉ hiện nhóm của đúng bước; bước không có nhóm thì không vẽ gì", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(EVALUATION)));
    const { unmount } = render(<StageMetrics jobId="job-1" groupId="ST-CAMERA-POSE" />);
    expect(await screen.findByText("0.56 px")).toBeInTheDocument();
    expect(screen.queryByText("PSNR / SSIM / LPIPS")).toBeNull();
    unmount();
    const empty = render(<StageMetrics jobId="job-1" groupId="ST-PRIVACY-GATE" />);
    await screen.findByText("Đang tải chỉ số…").then(() => undefined, () => undefined);
    await vi.waitFor(() => expect(empty.container.querySelector("section")).toBeNull());
    expect(empty.container.textContent).not.toContain("0.56 px");
  });
});

describe("parseJobEvaluation", () => {
  it("giữ null cho chỉ số chưa đo và từ chối dữ liệu sai dạng", () => {
    const parsed = parseJobEvaluation(EVALUATION);
    expect(parsed.groups[1].metrics[0].value).toBeNull();
    expect(parsed.groups[0].metrics[0].verdict).toBe("ok");
    expect(() => parseJobEvaluation({ ...EVALUATION, groups: [{ group_id: "x", title: "X", status: "la", metrics: [] }] })).toThrow();
    expect(() => parseJobEvaluation({ job_id: "a" })).toThrow();
  });
});
