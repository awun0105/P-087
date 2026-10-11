/** Bảng đánh giá: hiện đúng số và kết luận; bước chưa đo không bị vẽ như có kết quả; dữ liệu sai dạng thành lỗi. */

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EvaluationCard, StageMetrics } from "@/features/studio/evaluation/EvaluationCard";
import { parseJobEvaluation } from "@/lib/api/studio";

const EVALUATION = {
  job_id: "job-1", project_id: "project-1", scene_name: "Kho A", job_status: "SUCCEEDED", scene_revision: "rev-002",
  generated_at: "2026-10-02T03:00:00Z", schema_version: "1.1", summary: [],
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

  it("hiển thị khối summary theo đúng thứ tự và tone phù hợp", async () => {
    const withSummary = {
      ...EVALUATION,
      summary: ["Cảnh báo 1: video rung", "Cảnh báo 2: frame tối"],
      groups: [
        {
          group_id: "ST-CAMERA-POSE", title: "Vị trí camera", status: "measured" as const, note: null,
          metrics: [
            { key: "pose.registered_ratio", label: "Ảnh dựng được", value: 30, unit: "%", display: "30%", meaning: "m", source: "self_check", verdict: "warn" as const, threshold: "≥ 50%", reference: null },
          ],
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async () => reply(withSummary)));
    const { container } = render(<EvaluationCard jobId="job-1" revision="rev-002" />);
    expect(await screen.findByText("Cảnh báo 1: video rung")).toBeInTheDocument();
    expect(screen.getByText("Cảnh báo 2: frame tối")).toBeInTheDocument();
    const notice = container.querySelector("[role='note']");
    expect(notice).not.toBeNull();
    expect(notice?.className).toContain("bg-ochre-soft");
  });

  it("không hiển thị khối summary khi summary rỗng", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ ...EVALUATION, summary: [] })));
    const { container } = render(<EvaluationCard jobId="job-1" revision="rev-002" />);
    await screen.findByText("Bảng đánh giá");
    expect(container.querySelector("[role='note']")).toBeNull();
  });

  it("hiển thị reference dưới meaning khi có và hiển thị các chỉ số hệ thống mới", async () => {
    const withRefAndSystem = {
      ...EVALUATION,
      groups: [
        {
          group_id: "ST-VISUAL-RECON", title: "Scene 3DGS", status: "measured" as const, note: null,
          metrics: [
            {
              key: "visual.novel_view_quality", label: "PSNR", value: 28.5, unit: "dB",
              display: "28.50 dB", meaning: "Góc nhìn mới.", source: "self_check", verdict: null, threshold: null,
              reference: "Các scene đã chạy: 25,35–30,00 dB (6 scene)",
            },
          ],
        },
        {
          group_id: "system", title: "Hệ thống", status: "measured" as const, note: null,
          metrics: [
            { key: "system.peak_ram", label: "RAM tối đa", value: 5.19, unit: "GB", display: "5,2 GB (bước scene_extract)", meaning: "m", source: "self_check", verdict: null, threshold: null, reference: null },
            { key: "system.peak_vram", label: "VRAM tối đa", value: 3.42, unit: "GB", display: "3,4 GB (bước scene_extract)", meaning: "m", source: "self_check", verdict: null, threshold: null, reference: null },
            { key: "system.config", label: "Cấu hình xử lý", value: null, unit: null, display: "tối đa 1.200 frame · 6.000.000 splat · 3.840 px", meaning: "m", source: "self_check", verdict: null, threshold: null, reference: null },
          ],
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async () => reply(withRefAndSystem)));
    render(<EvaluationCard jobId="job-1" revision="rev-002" />);
    expect(await screen.findByText("Các scene đã chạy: 25,35–30,00 dB (6 scene)")).toBeInTheDocument();
    expect(screen.getByText("5,2 GB (bước scene_extract)")).toBeInTheDocument();
    expect(screen.getByText("3,4 GB (bước scene_extract)")).toBeInTheDocument();
    expect(screen.getByText("tối đa 1.200 frame · 6.000.000 splat · 3.840 px")).toBeInTheDocument();
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
    expect(parsed.summary).toEqual([]);
    expect(parsed.groups[1].metrics[0].value).toBeNull();
    expect(parsed.groups[0].metrics[0].verdict).toBe("ok");
    expect(() => parseJobEvaluation({ ...EVALUATION, groups: [{ group_id: "x", title: "X", status: "la", metrics: [] }] })).toThrow();
    expect(() => parseJobEvaluation({ job_id: "a" })).toThrow();
  });

  it("parses optional summary and metric references", () => {
    const groups = EVALUATION.groups.map((group) => group.group_id === "ST-CAMERA-POSE"
      ? { ...group, metrics: [...group.metrics, {
          key: "reference.fixture", label: "Tham chiếu", value: 1, unit: null,
          display: "1", meaning: "Chỉ để kiểm kiểu dữ liệu.", reference: "Khoảng đã quan sát",
        }] }
      : group);
    const parsed = parseJobEvaluation({ ...EVALUATION, summary: ["Kiểm tra dữ liệu"], groups });
    expect(parsed.summary).toEqual(["Kiểm tra dữ liệu"]);
    expect(parsed.groups[0].metrics[2].reference).toBe("Khoảng đã quan sát");
    expect(parsed.groups[0].metrics[0].reference).toBeNull();
    expect(parseJobEvaluation({ ...EVALUATION, summary: undefined }).summary).toEqual([]);
  });
});
