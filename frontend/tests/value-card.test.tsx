/** Thẻ Giá trị: số đủ và thiếu, nhãn nguồn (đo / khai báo / chưa có), P2 luôn "đo, so với số thước", link tải thật. */

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ValueCard, figureText, p2GapText, p2Label, p4Label, sourceLabel } from "@/features/studio/value/ValueCard";
import type { Figure, ValueScorecard } from "@/lib/api/value";

const MISSING = (note: string): Figure => ({ value: null, unit: null, provenance: "unavailable", note });

function scorecard(overrides: Partial<ValueScorecard> = {}): ValueScorecard {
  const base: ValueScorecard = {
    job_id: "job-1",
    scene_name: "Kho A",
    generated_at: "2026-10-16T08:00:00Z",
    scene_revision: "rev-004",
    data_source: "self_capture",
    notes: "",
    north_star: {
      hands_on_minutes: { value: 2, unit: "phút", provenance: "measured", note: null },
      hands_on_before_ready_minutes: { value: 1, unit: "phút", provenance: "measured", note: null },
      hands_on_after_ready_minutes: { value: 1, unit: "phút", provenance: "measured", note: null },
      machine_minutes: { value: 10, unit: "phút", provenance: "measured", note: null },
      hardware: { gpu_name: "RTX 4090", vram_gb: null, cpu_count: null, ram_gb: null, peak_vram_gb: 10, peak_ram_gb: 8 },
      gpu_hours: { value: 0.16, unit: "giờ", provenance: "measured", note: null },
      cost_usd: { value: 0.5, unit: "USD", provenance: "declared", note: null },
      interventions: { transform_edit: 2 },
      interventions_total: { value: 2, unit: "lần", provenance: "measured", note: null },
    },
    p2: {
      gaps_checked: 2,
      gaps_agree: 1,
      missed_obstacles: 1,
      false_obstacles: 0,
      gap_results: [],
      max_distance_error_cm: { value: 1.5, unit: "cm", provenance: "declared", note: null },
      key_obstacles_with_collider: "2/2",
      unavailable_reason: null,
    },
    p3: {
      edit_to_retest_minutes: { value: 6, unit: "phút", provenance: "measured", note: null },
      moves: [],
      consistent: true,
      unavailable_reason: null,
    },
    p4: { level: 2, reasons: ["layout A còn 1 khe bỏ sót vật cản"] },
    manual_baseline_minutes: { value: 45, unit: "phút", provenance: "declared", note: null },
  };
  return { ...base, ...overrides };
}

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

describe("nhãn nguồn", () => {
  it("phân biệt đo, khai báo và chưa có; P2 không bao giờ là 'khai báo'", () => {
    expect(sourceLabel({ value: 1, unit: null, provenance: "measured", note: null })).toBe("đo");
    expect(sourceLabel({ value: 1, unit: null, provenance: "declared", note: null })).toBe("khai báo");
    expect(sourceLabel(MISSING("x"))).toBe("chưa có");
    expect(p2Label(scorecard().p2)).toBe("đo, so với số thước");
    expect(p2Label({ ...scorecard().p2, unavailable_reason: "chưa có ground truth" })).toBe("chưa có");
  });

  it("bậc L4 là khai báo tay, L0–L3 là đo", () => {
    expect(p4Label(4)).toBe("khai báo");
    expect(p4Label(3)).toBe("đo");
  });

  it("số thiếu dữ liệu hiện 'chưa đo được', không bao giờ là 0", () => {
    expect(figureText(MISSING("không có GPU"))).toBe("chưa đo được");
    expect(figureText({ value: 0, unit: "phút", provenance: "measured", note: null })).toBe("0 phút");
  });
});

describe("ValueCard", () => {
  beforeEach(() => { vi.unstubAllGlobals(); });

  it("hiện đủ số, nhãn nguồn và nhãn P2 đúng quy ước", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(scorecard())));
    render(<ValueCard jobId="job-1" revision="rev-004" />);

    const north = (await screen.findByText("Người")).closest("div")!.parentElement!;
    expect(within(north).getByText("2 phút")).toBeInTheDocument();
    expect(within(north).getAllByText("(đo)").length).toBeGreaterThanOrEqual(1);

    const machine = screen.getByText("Máy").closest("div")!;
    expect(within(machine).getByText(/10 phút/)).toBeInTheDocument();
    expect(within(machine).getByText(/RTX 4090/)).toBeInTheDocument();

    expect(screen.getByText("~$0.50")).toBeInTheDocument();
    expect(screen.getAllByText("(khai báo)")).toHaveLength(2); // cost_usd và mốc làm tay

    const p2 = screen.getByText("P2 · Độ đúng").closest("div")!.parentElement!;
    expect(within(p2).getByText("đo, so với số thước")).toBeInTheDocument();
    expect(within(p2).getByText(/khe khớp 1\/2 · bỏ sót 1 · giả 0/)).toBeInTheDocument();
    expect(within(p2).queryByText("khai báo")).not.toBeInTheDocument();
  });

  it("số chưa đo được hiện lý do, không hiện 0 phút", async () => {
    const card = scorecard({
      north_star: {
        ...scorecard().north_star,
        hands_on_minutes: MISSING("job chưa có lô thời gian thao tác"),
        machine_minutes: MISSING("job chưa có số đo thời gian máy"),
        cost_usd: MISSING("chưa khai báo đơn giá GPU/giờ"),
        hardware: { gpu_name: null },
      },
      p2: { ...scorecard().p2, unavailable_reason: "chưa có ground truth" },
      p3: { ...scorecard().p3, edit_to_retest_minutes: MISSING("chưa có layout B"), consistent: null, unavailable_reason: "chưa có ground truth" },
    });
    vi.stubGlobal("fetch", vi.fn(async () => reply(card)));
    render(<ValueCard jobId="job-1" revision="rev-004" />);

    expect(await screen.findByText("Máy")).toBeInTheDocument();
    expect(screen.getAllByText("chưa đo được").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/^0 phút/)).not.toBeInTheDocument();
    expect(screen.getByText("chưa khai báo đơn giá GPU/giờ")).toBeInTheDocument();
    expect(screen.getByText("job chưa có lô thời gian thao tác")).toBeInTheDocument();
    expect(screen.getAllByText("chưa có ground truth")).toHaveLength(2); // P2 và P3
    expect(screen.getByText("chưa có layout B")).toBeInTheDocument();
  });

  it("bậc 0–3 liệt kê điều kiện còn thiếu; bậc 4 hiện nhãn khai báo và không liệt kê", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(scorecard({ p4: { level: 2, reasons: ["layout A còn 1 khe bỏ sót vật cản"] } }))));
    const { unmount } = render(<ValueCard jobId="job-1" revision="rev-004" />);
    expect(await screen.findByText("L2")).toBeInTheDocument();
    expect(screen.getByText("layout A còn 1 khe bỏ sót vật cản")).toBeInTheDocument();
    unmount();

    vi.stubGlobal("fetch", vi.fn(async () => reply(scorecard({ p4: { level: 4, reasons: [] } }))));
    render(<ValueCard jobId="job-1" revision="rev-004" />);
    expect(await screen.findByText("L4")).toBeInTheDocument();
    const p4 = screen.getByText("P4 · Bậc sẵn sàng").closest("div")!.parentElement!;
    expect(within(p4).getByText("khai báo")).toBeInTheDocument();
    expect(within(p4).queryByText(/Chưa lên bậc tiếp/)).not.toBeInTheDocument();
  });

  it("nút tải là link thật tới API; nút mở Benchmark trỏ tới tab Studio của scene", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(scorecard())));
    render(<ValueCard jobId="job-1" revision="rev-004" />);

    const csv = await screen.findByRole("link", { name: /Tải CSV/ });
    expect(csv).toHaveAttribute("href", "/api/v1/jobs/job-1/value-metrics.csv");
    expect(screen.getByRole("link", { name: /Tải Markdown/ })).toHaveAttribute("href", "/api/v1/jobs/job-1/value-metrics.md");
    expect(screen.getByRole("link", { name: "Mở Benchmark" })).toHaveAttribute("href", "/scenes/job-1?tab=studio");
  });
});

describe("P2 khi chưa đo khe nào", () => {
  beforeEach(() => { vi.unstubAllGlobals(); });

  it("chưa đo khe nào thì không hiện 0/0 và bỏ sót 0", async () => {
    const card = scorecard({
      p2: { ...scorecard().p2, gaps_checked: 0, gaps_agree: 0, missed_obstacles: 0, false_obstacles: 0 },
    });
    vi.stubGlobal("fetch", vi.fn(async () => reply(card)));
    render(<ValueCard jobId="job-1" revision="rev-004" />);

    expect(await screen.findByText("chưa có khe kiểm nào được đo")).toBeInTheDocument();
    expect(screen.queryByText(/khe khớp 0\/0/)).not.toBeInTheDocument();
    expect(screen.queryByText(/bỏ sót 0/)).not.toBeInTheDocument();
    expect(p2Label({ ...card.p2, max_distance_error_cm: MISSING("chưa có đoạn đo thước") })).toBe("chưa có");
    expect(p2Label(card.p2)).toBe("đo, so với số thước"); // còn sai số kích thước đo được
    expect(p2GapText(card.p2)).toBeNull();
  });
});
