import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModeComparisonView } from "@/features/studio/ModeComparisonView";
import { getModeComparison } from "@/lib/api/studio";
import type { ModeComparison, ModeResult } from "@/lib/contracts/studio";

vi.mock("@/lib/api/studio", () => ({ getModeComparison: vi.fn() }));

function result(overrides: Partial<ModeResult> = {}): ModeResult {
  return { mode: "rgb_only", title: "MoGe-2 · Ước lượng tự động", status: "estimated", note: "Đề xuất từ ảnh, chưa phải số đo ngoài đời.", steps: ["Ước lượng độ sâu từ ảnh"], scale_m_per_sfm_unit: 3.044086185, relative_uncertainty: 0.0526, frames_used: 60, camera_height_mean_m: null, camera_height_range_m: null, ...overrides };
}

function comparison(modes: ModeResult[]): ModeComparison {
  return { job_id: "job-rgb", modes, difference: null, lidar_ground_truth_assisted: false };
}

beforeEach(() => vi.clearAllMocks());

describe("metric comparison provenance", () => {
  it("shows a MoGe estimate separately from the accepted estimate, without claiming manual measurement", async () => {
    vi.mocked(getModeComparison).mockResolvedValue(comparison([
      result(),
      result({ mode: "user_anchor", title: "Kết quả đã xác nhận", status: "confirmed", note: "Người dùng đã chấp nhận ước lượng MoGe-2. Kết quả vẫn là ước lượng, không phải số đo độc lập.", steps: [], camera_height_mean_m: 0.287193, camera_height_range_m: [0.027, 0.372] }),
      result({ mode: "lidar", title: "LiDAR", status: "missing", note: "Scene không có dữ liệu LiDAR.", steps: [], scale_m_per_sfm_unit: null, relative_uncertainty: null, frames_used: null }),
    ]));
    render(<ModeComparisonView jobId="job-rgb" />);
    await screen.findByText("Số đo & nguồn tỉ lệ mét");
    expect(screen.getByText("Ước lượng", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Đã xác nhận", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText("3.0441 m/đơn vị")).toHaveLength(2);
    expect(screen.getAllByText("±5.3%")).toHaveLength(2);
    expect(screen.getAllByText("60", { exact: true })).toHaveLength(2);
    expect(screen.getByText("0.287 m (0.03–0.37)")).toBeInTheDocument();
    expect(screen.queryByText(/Mô phỏng|P1|chưa triển khai|Anchor người dùng/)).toBeNull();
    expect(screen.queryByText("Đã đo", { exact: true })).toBeNull();
    const details = screen.getByText("Cách ước lượng").closest("details");
    expect(details).not.toHaveAttribute("open");
  });

  it("shows missing proposal without fabricated scale or uncertainty", async () => {
    vi.mocked(getModeComparison).mockResolvedValue(comparison([
      result({ status: "missing", scale_m_per_sfm_unit: null, relative_uncertainty: null, frames_used: null, note: "Job này chưa có đề xuất MoGe-2." }),
      result({ mode: "user_anchor", title: "Kết quả đã xác nhận", status: "missing", scale_m_per_sfm_unit: null, relative_uncertainty: null, frames_used: null, steps: [] }),
      result({ mode: "lidar", title: "LiDAR", status: "missing", scale_m_per_sfm_unit: null, relative_uncertainty: null, frames_used: null, steps: [] }),
    ]));
    render(<ModeComparisonView jobId="job-rgb" />);
    await screen.findByText("Chưa có đề xuất");
    expect(screen.queryByText(/m\/đơn vị|±/)).toBeNull();
    expect(screen.queryByText(/P1|chưa triển khai/)).toBeNull();
  });

  it("keeps manual measurement wording and LiDAR comparison numbers", async () => {
    const data = comparison([
      result({ status: "missing", scale_m_per_sfm_unit: null, relative_uncertainty: null, frames_used: null }),
      result({ mode: "user_anchor", title: "Kết quả đã xác nhận", status: "confirmed", note: "Khoảng cách do người dùng đo ngoài đời.", relative_uncertainty: null, frames_used: null, steps: [] }),
      result({ mode: "lidar", title: "LiDAR", status: "measured", relative_uncertainty: null, frames_used: null, steps: [] }),
    ]);
    data.difference = { scale_diff_percent: 2, floor_tilt_deg: 1, camera_height_diff_m: 0.1, check_segment_user_m: null, check_segment_lidar_m: null, check_segment_error_m: null };
    vi.mocked(getModeComparison).mockResolvedValue(data);
    render(<ModeComparisonView jobId="job-rgb" />);
    await screen.findByText("Khoảng cách do người dùng đo ngoài đời.");
    const heading = screen.getByText("Kết quả đã xác nhận so với LiDAR");
    expect(within(heading.parentElement!).getByText("2.00 %")).toBeInTheDocument();
    expect(screen.getByText("Đã đo", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText(/±/)).toBeNull();
  });
});
