/** Trang /benchmark: bảng một dòng một scene, lọc theo nguồn, trạng thái rỗng, số thiếu không hiện 0, link tải thật. */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BenchmarkPage } from "@/features/studio/value/BenchmarkPage";
import type { BenchmarkResponse, Figure, ValueScorecard } from "@/lib/api/value";

const MISSING = (note: string): Figure => ({ value: null, unit: null, provenance: "unavailable", note });

function row(overrides: Partial<ValueScorecard> & { job_id: string; scene_name: string }): ValueScorecard {
  const base: ValueScorecard = {
    job_id: "job-x",
    scene_name: "Scene",
    generated_at: "2026-10-16T08:00:00Z",
    scene_revision: "rev-004",
    data_source: "self_capture",
    notes: "",
    north_star: {
      hands_on_minutes: { value: 12.5, unit: "phút", provenance: "measured", note: null },
      hands_on_before_ready_minutes: { value: 5, unit: "phút", provenance: "measured", note: null },
      hands_on_after_ready_minutes: { value: 7.5, unit: "phút", provenance: "measured", note: null },
      machine_minutes: { value: 30, unit: "phút", provenance: "measured", note: null },
      hardware: { gpu_name: "RTX 4090", vram_gb: null, cpu_count: null, ram_gb: null, peak_vram_gb: 12, peak_ram_gb: 9 },
      gpu_hours: { value: 0.5, unit: "giờ", provenance: "measured", note: null },
      cost_usd: { value: 0.25, unit: "USD", provenance: "declared", note: null },
      interventions: { transform_edit: 3 },
      interventions_total: { value: 3, unit: "lần", provenance: "measured", note: null },
    },
    p2: {
      gaps_checked: 4,
      gaps_agree: 3,
      missed_obstacles: 1,
      false_obstacles: 0,
      gap_results: [],
      max_distance_error_cm: { value: 2.0, unit: "cm", provenance: "declared", note: null },
      key_obstacles_with_collider: "3/3",
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

const SUMMARY = {
  scenes: 2,
  hands_on_median_minutes: 12.5,
  hands_on_n: 2,
  machine_median_minutes_by_gpu: { "RTX 4090": 30 },
  machine_n_by_gpu: { "RTX 4090": 2 },
  gaps_agree_total: 3,
  gaps_total: 4,
  missed_total: 1,
  false_total: 0,
  scenes_at_least_l2: 2,
  scenes_at_least_l3: 0,
  manual_median_minutes: 45,
  manual_n: 1,
};

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

function bodyRows(): HTMLElement[] {
  const table = screen.getByRole("table");
  return within(table).getAllByRole("row").slice(1);
}

describe("BenchmarkPage", () => {
  beforeEach(() => { vi.unstubAllGlobals(); });

  it("một dòng một scene, ô tổng hợp và link tải thật tới API", async () => {
    const response: BenchmarkResponse = {
      rows: [
        row({ job_id: "job-1", scene_name: "Kho A" }),
        row({ job_id: "job-2", scene_name: "Phòng HF", data_source: "hf_room" }),
      ],
      summary: SUMMARY,
    };
    vi.stubGlobal("fetch", vi.fn(async () => reply(response)));
    render(<BenchmarkPage />);

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Kho A" })).toHaveAttribute("href", "/scenes/job-1");
    expect(screen.getByRole("link", { name: /Tải CSV/ })).toHaveAttribute("href", "/api/v1/value-metrics/benchmark.csv");
    expect(screen.getByRole("link", { name: /Tải Markdown/ })).toHaveAttribute("href", "/api/v1/value-metrics/benchmark.md");
    expect(screen.getByText("3/4 · 1 · 0")).toBeInTheDocument();
  });

  it("lọc theo nguồn dữ liệu chỉ giữ scene đúng nguồn", async () => {
    const response: BenchmarkResponse = {
      rows: [row({ job_id: "job-1", scene_name: "Kho A" }), row({ job_id: "job-2", scene_name: "Phòng HF", data_source: "hf_room" })],
      summary: SUMMARY,
    };
    vi.stubGlobal("fetch", vi.fn(async () => reply(response)));
    render(<BenchmarkPage />);
    await screen.findByRole("table");

    fireEvent.change(screen.getByLabelText("Nguồn dữ liệu"), { target: { value: "hf_room" } });

    expect(bodyRows()).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Phòng HF" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Kho A" })).not.toBeInTheDocument();
  });

  it("chưa có scene nào thì hiện đúng câu hướng dẫn", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ rows: [], summary: { ...SUMMARY, scenes: 0 } })));
    render(<BenchmarkPage />);

    expect(
      await screen.findByText("Chưa có scene nào được đưa vào benchmark. Bật 'Đưa vào benchmark' trong panel Benchmark của scene."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("số chưa đo được hiện 'chưa có' hoặc 'chưa đo được', không hiện 0", async () => {
    const missingRow = row({
      job_id: "job-3",
      scene_name: "Chưa đo",
      north_star: {
        ...row({ job_id: "x", scene_name: "x" }).north_star,
        machine_minutes: MISSING("job chưa có số đo thời gian máy"),
        hands_on_minutes: MISSING("job chưa có lô thời gian thao tác"),
        hardware: { gpu_name: null },
      },
      p2: { ...row({ job_id: "x", scene_name: "x" }).p2, unavailable_reason: "chưa có ground truth", gaps_checked: 0, gaps_agree: 0 },
      p3: { ...row({ job_id: "x", scene_name: "x" }).p3, consistent: null, unavailable_reason: "chưa có ground truth" },
      p4: { level: 0, reasons: ["chưa xác nhận tỉ lệ mét cho revision hiện tại"] },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        reply({
          rows: [missingRow],
          summary: { ...SUMMARY, scenes: 1, hands_on_median_minutes: null, hands_on_n: 0, gaps_total: 0, gaps_agree_total: 0, machine_median_minutes_by_gpu: {}, machine_n_by_gpu: {} },
        }),
      ),
    );
    render(<BenchmarkPage />);
    await screen.findByRole("table");

    const cells = bodyRows()[0].textContent ?? "";
    expect(cells).toContain("chưa đo được");
    expect(cells).toContain("chưa có");
    expect(cells).not.toContain("0/0");
    expect(screen.getByText("Người (trung vị, n = 0)").nextSibling?.textContent ?? "").toBe("chưa đo được");
    expect(screen.getByText("Khe khớp / bỏ sót / giả").nextSibling?.textContent ?? "").toBe("chưa đo được");
  });

  it("bậc L4 hiện nhãn khai báo ở bảng", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ rows: [row({ job_id: "job-4", scene_name: "L4", p4: { level: 4, reasons: [] } })], summary: SUMMARY })));
    render(<BenchmarkPage />);
    await screen.findByRole("table");

    expect(screen.getByText("(khai báo)")).toBeInTheDocument();
  });
});
