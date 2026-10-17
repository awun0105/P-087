import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreviewScene } from "@/features/studio/scene/PreviewScene";
import { getStageViews } from "@/lib/api/studio";
import type { StageView } from "@/lib/contracts/studio";

const viewer = vi.hoisted(() => ({
  props: [] as {
    initialCamera?: { position: number[]; target: number[] };
    cameras?: unknown[];
    displayRotation?: number[];
    extraControls?: import("react").ReactNode;
  }[],
}));
vi.mock("@/lib/api/studio", () => ({ getStageViews: vi.fn() }));
vi.mock("@/features/viewer/PlayCanvasScene", async (original) => ({
  ...(await original<typeof import("@/features/viewer/PlayCanvasScene")>()),
  usePlayCanvasCapability: () => ["ready", vi.fn()],
  PlayCanvasScene: (props: {
    initialCamera?: { position: number[]; target: number[] };
    cameras?: unknown[];
    extraControls?: import("react").ReactNode;
    onRuntime?: (runtime: { loaded: boolean; progress: number; graphicsBackend: string }) => void;
    onApp?: (app: unknown, controls?: unknown) => void;
  }) => {
    viewer.props.push(props);
    return (
      <div data-testid="viewer">
        <button
          type="button"
          data-testid="simulate-loaded"
          onClick={() => {
            props.onApp?.(null, {
              resetCamera: vi.fn(),
              gotoPose: vi.fn(),
              getCameraPose: () => ({ position: [1, 2, 3], target: [0, 0, 0], fov: 60 }),
            });
            props.onRuntime?.({ loaded: true, progress: 100, graphicsBackend: "webgl" });
          }}
        >
          Loaded
        </button>
        {props.extraControls}
      </div>
    );
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
  it("dùng hướng xác nhận của preview cho cả camera và nội dung; không lấy camera hệ mét", async () => {
    const rotation: [number, number, number, number] = [-Math.SQRT1_2, 0, 0, Math.SQRT1_2];
    vi.mocked(getStageViews).mockResolvedValue([
      cameraView,
      { ...cameraView, kind: "gaussian", stage_id: "ST-VISUAL-RECON", display_rotation_xyzw: rotation },
      { ...cameraView, kind: "gaussian", unit: "meter", cameras: [{ ...sfmCameras[0], center: [100, 200, 300] }] },
    ]);
    const { rerender } = render(<PreviewScene jobId="job-a" contentUrl="/scene.sog" filename="scene.sog" />);
    await screen.findByTestId("viewer");
    expect(viewer.props.at(-1)?.displayRotation).toEqual(rotation);
    viewer.props.at(-1)!.initialCamera!.position.forEach((value, axis) => expect(value).toBeCloseTo([1, 3, -2][axis]));
    // Caller cung cấp camera hệ mét: không áp hướng SfM lên nó lần nữa.
    rerender(<PreviewScene jobId="job-a" sourceFrame="z_up" cameras={sfmCameras} contentUrl="/metric.sog" filename="metric.sog" />);
    expect(viewer.props.at(-1)?.displayRotation).toBeUndefined();
    expect(viewer.props.at(-1)?.initialCamera?.position).toEqual([1, 3, -2]);
  });

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

  it("hiển thị nút lưu góc nhìn mặc định khi có onSaveDefaultCamera", async () => {
    const handleSave = vi.fn();
    render(
      <PreviewScene
        contentUrl="/scene.sog"
        filename="scene.sog"
        onSaveDefaultCamera={handleSave}
      />,
    );
    fireEvent.click(screen.getByTestId("simulate-loaded"));
    const saveBtn = await screen.findByRole("button", { name: "Đặt làm góc nhìn mặc định" });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);
    expect(handleSave).toHaveBeenCalledTimes(1);
  });

  it("chuyển đổi trạng thái bookmark: gỡ bookmark khi đang có bookmark và đặt bookmark khi chưa có", async () => {
    const handleToggle = vi.fn();
    const bookmarkPose = { position: [2, 3, 4] as [number, number, number], target: [0, 0, 0] as [number, number, number], fov: 60 };

    // Đang có bookmark -> nút hiện 'Gỡ góc nhìn mặc định', bấm sẽ gọi handleToggle(false)
    const { rerender } = render(
      <PreviewScene
        contentUrl="/scene.sog"
        filename="scene.sog"
        currentBookmark={bookmarkPose}
        onToggleBookmark={handleToggle}
      />,
    );
    fireEvent.click(screen.getByTestId("simulate-loaded"));
    const unbookmarkBtn = await screen.findByRole("button", { name: "Gỡ bookmark" });
    expect(unbookmarkBtn).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(unbookmarkBtn);
    expect(handleToggle).toHaveBeenCalledWith(false, expect.anything());

    // Đã gỡ bookmark (currentBookmark = null) -> nút chuyển thành 'Đặt làm góc nhìn mặc định', bấm gọi handleToggle(true)
    handleToggle.mockClear();
    rerender(
      <PreviewScene
        contentUrl="/scene.sog"
        filename="scene.sog"
        currentBookmark={null}
        onToggleBookmark={handleToggle}
      />,
    );
    const bookmarkBtn = screen.getByRole("button", { name: "Bookmark góc nhìn hiện tại" });
    expect(bookmarkBtn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(bookmarkBtn);
    expect(handleToggle).toHaveBeenCalledWith(true, expect.anything());
  });

  it("quay về vị trí ban đầu: nhảy về currentBookmark nếu có, hoặc fallbackInitialCamera nếu đã gỡ bookmark", async () => {
    let capturedControls: { resetCamera: ReturnType<typeof vi.fn>; gotoPose: ReturnType<typeof vi.fn> } | null = null;
    const bookmarkPose = { position: [5, 5, 5] as [number, number, number], target: [1, 1, 1] as [number, number, number], fov: 60 };
    const initialPose = { position: [10, 10, 10] as [number, number, number], target: [0, 0, 0] as [number, number, number], fov: 60 };

    const { rerender } = render(
      <PreviewScene
        contentUrl="/scene.sog"
        filename="scene.sog"
        currentBookmark={bookmarkPose}
        fallbackInitialCamera={initialPose}
        onControlsReady={(ctrl) => { capturedControls = ctrl as typeof capturedControls; }}
      />,
    );
    fireEvent.click(screen.getByTestId("simulate-loaded"));

    // Có bookmark: nút có tên "Về góc nhìn đã lưu", bấm sẽ gọi gotoPose(bookmarkPose)
    const resetSavedBtn = await screen.findByRole("button", { name: "Về góc nhìn đã lưu" });
    fireEvent.click(resetSavedBtn);
    expect(capturedControls!.gotoPose).toHaveBeenCalledWith(bookmarkPose);

    // Gỡ bookmark: currentBookmark = null, nút chuyển thành "Về vị trí ban đầu", bấm sẽ gọi gotoPose(fallbackInitialCamera)
    capturedControls!.gotoPose.mockClear();
    rerender(
      <PreviewScene
        contentUrl="/scene.sog"
        filename="scene.sog"
        currentBookmark={null}
        fallbackInitialCamera={initialPose}
        onControlsReady={(ctrl) => { capturedControls = ctrl as typeof capturedControls; }}
      />,
    );
    const resetInitialBtn = screen.getByRole("button", { name: "Về vị trí ban đầu" });
    fireEvent.click(resetInitialBtn);
    expect(capturedControls!.gotoPose).toHaveBeenCalledWith(initialPose);
  });
  it("R resets once inside this viewport and ignores typing, modifiers and outside focus", async () => {
    let controls: { gotoPose: ReturnType<typeof vi.fn> } | null = null;
    const bookmark = { position: [1, 2, 3] as [number, number, number], target: [0, 0, 0] as [number, number, number], fov: 85 };
    const { container } = render(<PreviewScene contentUrl="/scene.sog" filename="scene.sog" currentBookmark={bookmark} onControlsReady={(next) => { controls = next as typeof controls; }} />);
    fireEvent.click(screen.getByTestId("simulate-loaded"));
    const upstreamReset = vi.fn();
    window.addEventListener("keydown", upstreamReset);
    try {
      const viewport = container.firstElementChild as HTMLElement;
      viewport.focus();
      fireEvent.keyDown(viewport, { key: "r" });
      expect(controls!.gotoPose).toHaveBeenCalledTimes(1);
      expect(controls!.gotoPose).toHaveBeenCalledWith(bookmark);
      expect(upstreamReset).not.toHaveBeenCalled();
      fireEvent.keyDown(viewport, { key: "r", ctrlKey: true });
      fireEvent.keyDown(document.body, { key: "r" });
      const input = document.createElement("input");
      viewport.append(input);
      fireEvent.keyDown(input, { key: "r" });
      expect(controls!.gotoPose).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("keydown", upstreamReset);
    }
  });

});
