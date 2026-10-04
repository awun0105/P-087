/** Kiểm tra chọn đúng artifact và nhãn đơn vị; không chạy GPU trong jsdom. */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StageViewer } from "@/features/studio/StageViewer";
import { getStageViews } from "@/lib/api/studio";
import type { StageView } from "@/lib/contracts/studio";

vi.mock("@/lib/api/studio", () => ({ getStageViews: vi.fn() }));
vi.mock("@/features/viewer/PlayCanvasScene", () => ({ usePlayCanvasCapability: () => ["available", vi.fn()], PlayCanvasScene: () => <div>Gaussian renderer</div> }));
vi.mock("@/features/studio/MetricSceneView", () => ({ MetricSceneView: () => <div>Metric renderer</div> }));
const cameras: StageView = { stage_id: "ST-CAMERA-POSE", kind: "cameras", title: "Camera", note: "SfM", unit: "arbitrary", refs: [], cameras: [{ frame_id: 0, center: [0, 0, 0], rotation_xyzw: [0, 0, 0, 1] }] };
const gaussian: StageView = { stage_id: "ST-VISUAL-RECON", kind: "gaussian", title: "Gaussian gốc", note: "Raw", unit: "arbitrary", refs: [{ artifact_type: "GaussianSOG", artifact_uri: "artifact://jobs/job-a/attempts/a1/scene.sog", artifact_checksum: `sha256:${"a".repeat(64)}` }], cameras: [] };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getStageViews).mockResolvedValue([cameras, gaussian]); });

describe("stage viewer selection", () => {
  it("lọc đúng stage và tab đang hiển thị có aria-selected", async () => {
    render(<StageViewer jobId="job-a" stageId="ST-CAMERA-POSE" />);
    expect(await screen.findByRole("img", { name: "Quỹ đạo camera nhìn từ trên xuống" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Camera" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: "Gaussian gốc" })).toBeNull();
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
    expect(screen.getByText(/Đơn vị: tùy ý \(SfM\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Đơn vị: mét\./)).toBeNull();
  });

  it("6 có view hệ mét ưu tiên derivative, không dùng fallback", async () => {
    vi.mocked(getStageViews).mockResolvedValue([cameras, gaussian, { ...gaussian, stage_id: "ST-METRIC-CANONICALIZE", title: "Hệ mét", unit: "meter", note: "Canonical" }]);
    render(<StageViewer jobId="job-a" stageId="ST-METRIC-CANONICALIZE" fallbackStageId="ST-VISUAL-RECON" />);
    expect(await screen.findByText("Metric renderer")).toBeInTheDocument();
    expect(screen.getByText(/Đơn vị: mét\./)).toBeInTheDocument();
    expect(screen.queryByText(/Đang xem lại Gaussian gốc/)).toBeNull();
  });
});
