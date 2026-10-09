/** Bản xem 3DGS mở đầu bên trong scene: camera lấy từ quỹ đạo COLMAP của job, viewer dựng sau khi có camera. */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreviewScene } from "@/features/studio/scene/PreviewScene";
import { getStageViews } from "@/lib/api/studio";
import type { StageView } from "@/lib/contracts/studio";

const viewer = vi.hoisted(() => ({ props: [] as { initialCamera?: { position: number[]; target: number[] }; cameras?: unknown[] }[] }));
vi.mock("@/lib/api/studio", () => ({ getStageViews: vi.fn() }));
vi.mock("@/features/viewer/PlayCanvasScene", async (original) => ({
  ...(await original<typeof import("@/features/viewer/PlayCanvasScene")>()),
  usePlayCanvasCapability: () => ["ready", vi.fn()],
  PlayCanvasScene: (props: { initialCamera?: { position: number[]; target: number[] }; cameras?: unknown[] }) => {
    viewer.props.push(props);
    return <div data-testid="viewer" />;
  },
}));

const identity: [number, number, number, number] = [0, 0, 0, 1];
const sfmCameras = [
  { frame_id: 0, center: [1, 2, 3] as [number, number, number], rotation_xyzw: identity },
  { frame_id: 1, center: [4, 2, 3] as [number, number, number], rotation_xyzw: identity },
];
const cameraView: StageView = { stage_id: "ST-CAMERA-POSE", kind: "cameras", title: "Camera", note: "", unit: "arbitrary", refs: [], cameras: sfmCameras };

beforeEach(() => {
  vi.clearAllMocks();
  viewer.props = [];
});

describe("PreviewScene mở đầu bên trong scene", () => {
  it("chờ quỹ đạo camera của job rồi mới dựng viewer, đặt camera tại frame quay đầu tiên", async () => {
    let resolve!: (views: StageView[]) => void;
    vi.mocked(getStageViews).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<PreviewScene jobId="job-a" contentUrl="/scene.sog" filename="scene.sog" />);
    expect(screen.queryByTestId("viewer")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Đang tải bản xem 3DGS");

    resolve([cameraView]);

    expect(await screen.findByTestId("viewer")).toBeInTheDocument();
    expect(viewer.props).toHaveLength(1);
    // Hệ COLMAP sang không gian hiển thị: (x, y, z) → (−x, −y, z).
    expect(viewer.props[0].initialCamera?.position).toEqual([-1, -2, 3]);
    expect(viewer.props[0].cameras).toHaveLength(2);
  });

  it("không lấy được camera thì vẫn dựng viewer với camera mặc định, không treo ở màn tải", async () => {
    vi.mocked(getStageViews).mockRejectedValue(new Error("mất kết nối"));
    render(<PreviewScene jobId="job-a" contentUrl="/scene.sog" filename="scene.sog" />);
    expect(await screen.findByTestId("viewer")).toBeInTheDocument();
    expect(viewer.props[0].initialCamera).toBeUndefined();
  });

  it("caller đã cấp camera hoặc không có jobId thì không tải thêm và dựng ngay", async () => {
    render(<PreviewScene contentUrl="/scene.sog" filename="scene.sog" />);
    await waitFor(() => expect(screen.getByTestId("viewer")).toBeInTheDocument());
    render(<PreviewScene jobId="job-a" cameras={sfmCameras} contentUrl="/scene.sog" filename="scene.sog" />);
    expect(screen.getAllByTestId("viewer")).toHaveLength(2);
    expect(getStageViews).not.toHaveBeenCalled();
  });
});
