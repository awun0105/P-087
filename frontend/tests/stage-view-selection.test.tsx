/** Kiểm tra chọn đúng artifact và ẩn thông tin dư thừa; không chạy GPU trong jsdom. */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StageViewer } from "@/features/studio/StageViewer";
import { getStageViews } from "@/lib/api/studio";
import type { StageView } from "@/lib/contracts/studio";

vi.mock("@/lib/api/studio", () => ({ getStageViews: vi.fn() }));
vi.mock("@/features/viewer/PlayCanvasScene", () => ({
  usePlayCanvasCapability: () => ["available", vi.fn()],
  PlayCanvasScene: () => <div>Gaussian renderer</div>,
  INITIAL_RUNTIME: { loaded: false, progress: 0, graphicsBackend: "unknown", hasCollision: false, walkAllowed: false, cameraMode: "orbit" },
}));
vi.mock("@/features/studio/MetricSceneView", () => ({ MetricSceneView: () => <div>Metric renderer</div> }));
const cameras: StageView = { stage_id: "ST-CAMERA-POSE", kind: "cameras", title: "Camera", note: "SfM", unit: "arbitrary", refs: [], cameras: [{ frame_id: 0, center: [0, 0, 0], rotation_xyzw: [0, 0, 0, 1] }] };
const gaussian: StageView = { stage_id: "ST-VISUAL-RECON", kind: "gaussian", title: "Gaussian gốc", note: "Raw", unit: "arbitrary", refs: [{ artifact_type: "GaussianSOG", artifact_uri: "artifact://jobs/job-a/attempts/a1/scene.sog", artifact_checksum: `sha256:${"a".repeat(64)}` }], cameras: [] };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getStageViews).mockResolvedValue([cameras, gaussian]); });

describe("stage viewer selection", () => {
  it("bước COLMAP báo số lần tự thử lại và vùng thiếu ảnh khi mô hình được nhận kèm cảnh báo (T-071)", async () => {
    vi.mocked(getStageViews).mockResolvedValue([{ ...cameras, retry_count: 2, registration_warning: true, registered_ratio: 0.41 }, gaussian]);
    render(<StageViewer jobId="job-a" stageId="ST-CAMERA-POSE" />);
    expect(await screen.findByText("Đã tự thử lại ghép ảnh (2 lần)")).toBeInTheDocument();
    expect(screen.getByText("Vùng thiếu ảnh có thể bị mờ hoặc thủng (COLMAP dựng được vị trí cho 41% ảnh).")).toBeInTheDocument();
  });

  it("không báo thử lại khi lần ghép đầu đã đạt", async () => {
    vi.mocked(getStageViews).mockResolvedValue([{ ...cameras, retry_count: 0, registration_warning: false, registered_ratio: 0.9 }, gaussian]);
    render(<StageViewer jobId="job-a" stageId="ST-CAMERA-POSE" />);
    expect(await screen.findByRole("img", { name: "Quỹ đạo camera nhìn từ trên xuống" })).toBeInTheDocument();
    expect(screen.queryByText(/Đã tự thử lại ghép ảnh/)).toBeNull();
    expect(screen.queryByText(/Vùng thiếu ảnh/)).toBeNull();
  });

  it("lọc đúng stage và ẩn thanh chọn khi chỉ có một kết quả", async () => {
    render(<StageViewer jobId="job-a" stageId="ST-CAMERA-POSE" />);
    expect(await screen.findByRole("img", { name: "Quỹ đạo camera nhìn từ trên xuống" })).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByText("SfM")).toBeNull();
    expect(screen.queryByRole("tab", { name: "Gaussian gốc" })).toBeNull();
  });

  it("giữ thanh chọn khi có nhiều kết quả và chuyển được lớp xem", async () => {
    render(<StageViewer jobId="job-a" />);
    expect(await screen.findByRole("tab", { name: "Gaussian gốc" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Camera" }));
    expect(screen.getByRole("tab", { name: "Camera" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("img", { name: "Quỹ đạo camera nhìn từ trên xuống" })).toBeInTheDocument();
  });

  it("bỏ tiêu đề và mô tả collision thừa, giữ vùng xem", async () => {
    vi.mocked(getStageViews).mockResolvedValue([{ ...gaussian, stage_id: "ST-RGB-GEOMETRY", kind: "mesh", title: "Collision mesh (REC-05)", note: "Mesh va chạm thô cho Isaac; sàn là mặt phẳng z = 0 do Isaac tạo, không nằm trong mesh.", unit: "meter" }]);
    render(<StageViewer jobId="job-a" stageId="ST-RGB-GEOMETRY" />);
    expect(await screen.findByRole("tabpanel")).toBeInTheDocument();
    expect(screen.queryByText("Collision mesh (REC-05)")).toBeNull();
    expect(screen.queryByText(/Mesh va chạm thô cho Isaac/)).toBeNull();
    expect(screen.queryByText(/Đơn vị: mét/)).toBeNull();
  });

  it("thiếu view cho stage không mount kết quả bước khác", async () => {
    render(<StageViewer jobId="job-a" stageId="ST-RGB-GEOMETRY" />);
    expect(await screen.findByText(/API chưa cung cấp lớp xem/)).toBeInTheDocument();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByText("Gaussian renderer")).toBeNull();
  });

  it("6 chưa có derivative hiển thị cảnh báo và giữ đơn vị SfM", async () => {
    render(<StageViewer jobId="job-a" stageId="ST-METRIC-CANONICALIZE" fallbackStageId="ST-VISUAL-RECON" />);
    expect(await screen.findByText(/Đang xem lại Gaussian gốc, đơn vị SfM/)).toBeInTheDocument();
    expect(screen.queryByText(/Đơn vị: tùy ý \(SfM\)/)).toBeNull();
    expect(screen.queryByText(/Đơn vị: mét\./)).toBeNull();
  });

  it("6 có view hệ mét ưu tiên derivative, không dùng fallback", async () => {
    vi.mocked(getStageViews).mockResolvedValue([cameras, gaussian, { ...gaussian, stage_id: "ST-METRIC-CANONICALIZE", title: "Hệ mét", unit: "meter", note: "Canonical" }]);
    render(<StageViewer jobId="job-a" stageId="ST-METRIC-CANONICALIZE" fallbackStageId="ST-VISUAL-RECON" />);
    expect(await screen.findByText("Metric renderer")).toBeInTheDocument();
    expect(screen.queryByText("Canonical")).toBeNull();
    expect(screen.queryByText(/Đơn vị: mét\./)).toBeNull();
    expect(screen.queryByText(/Đang xem lại Gaussian gốc/)).toBeNull();
  });
});
