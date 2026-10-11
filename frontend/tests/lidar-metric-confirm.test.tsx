/** Xác nhận tỉ lệ cho job có gói LiDAR (ADR 0009): không chọn điểm, một nút xác nhận, hiện độ lệch pose ↔ quỹ đạo. */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LidarMetricConfirm, lidarMetricInput } from "@/features/studio/LidarMetricConfirm";
import { confirmMetric, previewMetric } from "@/lib/api/studio";
import type { MetricPreview, MetricProposal } from "@/lib/contracts/studio";

vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  previewMetric: vi.fn(), confirmMetric: vi.fn(),
}));

const proposal: MetricProposal = {
  status: "ESTIMATED", job_id: "job-lidar", method: "lidar_trajectory_alignment",
  scale_m_per_sfm_unit: 1.0003, frame_dispersion: 0, relative_uncertainty: 0.002, frames_used: 100, pairs_used: 100,
  floor: { points: [[0, 0, 0], [1, 0, 0], [0, 1, 0]], residual_m: 0, support_points: 9000 },
  segments: { point_a: [0, 0, 0], point_b: [2, 0, 0], distance_m: 2, check_a: [0, 1, 0], check_b: [1.5, 1, 0], check_distance_m: 1.5 },
  alignment: { trajectory_origin: "ground_truth", input_frames: 100, registered_frames: 100, offset_median_m: 0.08, offset_p90_m: 0.15, offset_max_m: 0.22, path_length_m: 49.5 },
};
const preview: MetricPreview = {
  preview_checksum: "sha256:preview", scale_m_per_sfm_unit: 1.0003, floor_residual_m: 0, measured_distance_m: 2,
  camera_height_min_m: 0.52, camera_height_max_m: 0.61, distance_source: "lidar_trajectory", check_measured_m: 1.5,
  check_error_m: 0, check_tolerance_m: 0.05, check_passed: true, warnings: ["Tỉ lệ và mặt sàn lấy từ gói LiDAR"],
};

beforeEach(() => { vi.clearAllMocks(); vi.mocked(previewMetric).mockResolvedValue(preview); });
afterEach(cleanup);

describe("xác nhận tỉ lệ từ LiDAR", () => {
  it("dựng đúng đầu vào từ đề xuất, không cần điểm nào của người dùng", () => {
    const input = lidarMetricInput(proposal)!;
    expect(input.distance_source).toBe("lidar_trajectory");
    expect(input.point_b).toEqual([2, 0, 0]);
    expect(lidarMetricInput({ ...proposal, segments: null })).toBeNull();
  });

  it("hiện số frame khớp và độ lệch pose, rồi xác nhận bằng một nút", async () => {
    vi.mocked(confirmMetric).mockResolvedValue({} as never);
    const done = vi.fn();
    render(<LidarMetricConfirm jobId="job-lidar" proposal={proposal} onConfirmed={done} />);
    expect(screen.getByText("100/100")).toBeInTheDocument();
    expect(screen.getByText(/trung vị 8 cm · lớn nhất 22 cm/)).toBeInTheDocument();
    expect(screen.getByText("Quỹ đạo chuẩn của dataset")).toBeInTheDocument();
    const button = await screen.findByRole("button", { name: /Xác nhận tỉ lệ từ LiDAR/ });
    expect(previewMetric).toHaveBeenCalledWith("job-lidar", expect.objectContaining({ distance_source: "lidar_trajectory" }));
    fireEvent.click(button);
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(confirmMetric).toHaveBeenCalledWith("job-lidar", expect.objectContaining({ distance_m: 2 }), "sha256:preview");
  });

  it("lỗi tính tỉ lệ hiện ra và không có nút xác nhận", async () => {
    vi.mocked(previewMetric).mockRejectedValue(new Error("Khoảng cách không khớp đề xuất"));
    render(<LidarMetricConfirm jobId="job-lidar" proposal={proposal} onConfirmed={vi.fn()} />);
    expect(await screen.findByText("Khoảng cách không khớp đề xuất")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Xác nhận tỉ lệ từ LiDAR/ })).toBeNull();
  });
});
