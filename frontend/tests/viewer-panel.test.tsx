/**
 * Test cho màn hình viewer (PRODUCT-06).
 *
 * `SceneCanvas` bị thay bằng stub: jsdom không có WebGL, và điều cần khoá ở đây
 * là hành vi của panel — chuyển view, ẩn/hiện layer, và cảnh báo thiếu bằng chứng
 * Brush — chứ không phải bản thân Three.js.
 *
 * Cảnh báo Brush là test quan trọng nhất: nếu nó biến mất, một visual tổng hợp
 * có thể bị đọc thành bằng chứng AC-11.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/features/viewer/SceneCanvas", () => ({
  SceneCanvas: ({ mode }: { mode: string }) => <div data-testid="canvas-stub">canvas:{mode}</div>,
}));

// Engine thật không dựng được trong jsdom; chỉ cần biết createViewer có được gọi
// và có destroy khi unmount. Phần render 3D thật kiểm bằng browser smoke riêng.
type ViewerOptions = {
  renderer?: string;
  ui?: boolean;
  contentUrl?: string;
  collisionUrl?: string;
};
type ViewerState = {
  loaded: boolean;
  progress: number;
  hasCollision: boolean;
  walkAllowed: boolean;
};
const runtime = {
  state: { loaded: true, progress: 100, hasCollision: true, walkAllowed: true } as ViewerState,
  events: { on: vi.fn(() => ({ off: vi.fn() })) },
  destroy: vi.fn(),
  frameScene: vi.fn(),
};
const createViewer = vi.fn(async (_options?: ViewerOptions) => runtime);
vi.mock("@playcanvas/supersplat-viewer/viewer", () => ({
  createViewer: (options?: ViewerOptions) => createViewer(options),
}));

const { ViewerPanel } = await import("@/features/viewer/ViewerPanel");
const { buildFixtureScene } = await import("./fixtures/scene");

describe("ViewerPanel", () => {
  beforeEach(() => {
    // jsdom không cấp WebGL; test nào cần nhánh "có WebGL" thì tự ghi đè.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  it("cảnh báo khi visual chưa phải bằng chứng Brush", () => {
    render(<ViewerPanel scene={buildFixtureScene()} />);
    const banner = screen.getByTestId("brush-proof-absent");
    expect(banner).toHaveTextContent("Chưa có bằng chứng 3DGS thật");
    expect(banner).toHaveTextContent("brush_compatibility_proof=false");
  });

  it("không cảnh báo khi visual thật sự có cờ Brush", () => {
    const scene = buildFixtureScene();
    scene.visual = { ...scene.visual, brush_compatibility_proof: true };
    render(<ViewerPanel scene={scene} />);
    expect(screen.queryByTestId("brush-proof-absent")).toBeNull();
  });

  it("hiện trạng thái suy giảm khi không có WebGL, không phải canvas trắng", () => {
    render(<ViewerPanel scene={buildFixtureScene()} />);
    const degraded = screen.getByTestId("webgl-unavailable");
    expect(degraded).toHaveTextContent("không phải bằng chứng render");
    expect(screen.queryByTestId("canvas-stub")).toBeNull();
  });

  it("dựng canvas khi có WebGL", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    render(<ViewerPanel scene={buildFixtureScene()} />);
    expect(screen.getByTestId("canvas-stub")).toHaveTextContent("canvas:COLLIDER");
  });

  it("đổi view mode sang Geometry mesh", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "Geometry mesh" }));
    expect(screen.getByTestId("canvas-stub")).toHaveTextContent("canvas:GEOMETRY");
  });

  it("hiện revision canonical đang xem", () => {
    render(<ViewerPanel scene={buildFixtureScene()} />);
    expect(screen.getByTestId("scene-revision")).toHaveTextContent("rev-001");
  });

  it("ẩn được một layer và giữ canonical state nguyên vẹn", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    render(<ViewerPanel scene={buildFixtureScene()} />);
    const toggle = screen.getByLabelText(/hiện Fixture Pallet — AABB/);
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    // Ẩn/hiện là lựa chọn xem: không đụng SceneIR, nên revision không đổi.
    expect(toggle).not.toBeChecked();
    expect(screen.getByTestId("scene-revision")).toHaveTextContent("rev-001");
  });

  it("hiện tên object khi chọn layer để sửa transform", () => {
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "Fixture Pallet — AABB" }));
    expect(screen.getByLabelText("translation xyz")).toBeDefined();
  });

  it("báo lỗi tại chỗ khi toạ độ nhập sai định dạng", () => {
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "Fixture Pallet — AABB" }));
    fireEvent.change(screen.getByLabelText("translation xyz"), { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu thành revision mới" }));
    expect(screen.getByRole("alert")).toHaveTextContent("ba số");
  });

  it("chưa chọn object thì không hiện ô nhập toạ độ", () => {
    render(<ViewerPanel scene={buildFixtureScene()} />);
    expect(screen.queryByLabelText("translation xyz")).toBeNull();
  });
});

/**
 * Ranh giới renderer (PRODUCT-06 §13.1): Visual đi qua PlayCanvas theo
 * `INTEGRATION_PLAYBOOK:745`, nhưng thiếu WebGL thì phải rơi về trạng thái suy
 * giảm chứ không được để canvas trắng — cùng tiêu chuẩn các view kỹ thuật đang có.
 */
describe("ranh giới renderer", () => {
  beforeEach(() => {
    createViewer.mockClear();
    runtime.state = { loaded: true, progress: 100, hasCollision: true, walkAllowed: true };
  });

  it("Visual dùng PlayCanvas khi có WebGL, với renderer webgl tường minh", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "3DGS Visual" }));
    expect(await screen.findByTestId("playcanvas-scene")).toHaveAttribute("data-engine", "playcanvas");
    await vi.waitFor(() => expect(createViewer).toHaveBeenCalledTimes(1));
    expect(createViewer.mock.calls[0][0]).toMatchObject({ renderer: "webgl", ui: false });
  });

  it("Visual không có WebGL thì báo suy giảm, không để canvas trắng", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "3DGS Visual" }));
    expect(screen.getByTestId("webgl-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("playcanvas-scene")).toBeNull();
  });

  it("PlayCanvas khởi tạo lỗi thì nói rõ, không âm thầm rơi về view khác", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    createViewer.mockRejectedValueOnce(new Error("device lost"));
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "3DGS Visual" }));
    expect(await screen.findByTestId("playcanvas-unavailable")).toHaveTextContent(
      "không phải bằng chứng thiếu 3DGS",
    );
  });

  it("cảnh báo thiếu bằng chứng Brush vẫn hiện ở view Visual", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "3DGS Visual" }));
    expect(screen.getByTestId("brush-proof-absent")).toBeInTheDocument();
  });
});

/**
 * Regression: `onFailed` nằm trong deps của effect tạo viewer. Nếu identity đổi
 * mỗi lần render thì mọi thao tác UI đều tạo lại viewer, tức tải lại toàn bộ SOG.
 * Bug này đã tồn tại và chỉ lộ ra khi có test render lại sau mount.
 */
it("re-render không được tạo lại PlayCanvas viewer", async () => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
  const scene = buildFixtureScene();
  const { rerender } = render(<ViewerPanel scene={scene} />);
  fireEvent.click(screen.getByRole("button", { name: "3DGS Visual" }));
  await screen.findByTestId("playcanvas-scene");
  await vi.waitFor(() => expect(createViewer).toHaveBeenCalledTimes(1));

  // Gõ vào ô filter: đây là thao tác nhẹ nhất nhưng vẫn re-render ViewerPanel.
  fireEvent.change(screen.getByPlaceholderText("lọc layer…"), { target: { value: "Pallet" } });
  rerender(<ViewerPanel scene={scene} />);

  expect(createViewer).toHaveBeenCalledTimes(1);
});

/**
 * Tiến trình và collider phải đến từ `ViewerHandle.state` / `collisionUrl` của thư viện,
 * không tự bịa. Nếu `collisionUrl` không được truyền thì Single Scene Graph chưa có
 * gì thật, dù URL có tồn tại.
 */
describe("tiến trình và collider từ thư viện", () => {
  beforeEach(() => {
    createViewer.mockClear();
    runtime.state = { loaded: false, progress: 42, hasCollision: false, walkAllowed: false };
  });

  it("truyền collisionUrl của environment để collider nằm trong cùng app với SOG", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "3DGS Visual" }));
    await screen.findByTestId("playcanvas-scene");
    await vi.waitFor(() => expect(createViewer).toHaveBeenCalledTimes(1));
    const options = createViewer.mock.calls[0][0];
    expect(options?.collisionUrl).toContain("/artifacts/content");
    expect(options?.collisionUrl).toContain(encodeURIComponent(buildFixtureScene().scene.environment.collider_ref!.artifact_uri));
  });

  it("hiện phần trăm lấy từ state.progress, không phải số tự tính", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "3DGS Visual" }));
    await screen.findByTestId("playcanvas-scene");
    const progress = await screen.findByTestId("viewer-progress");
    expect(progress).toHaveTextContent("42%");
    const bar = progress.querySelector<HTMLElement>("[style]");
    expect(bar?.style.width).toBe("42%");
  });

  it("báo đã tải xong khi state.loaded, kèm trạng thái collider", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    runtime.state = { loaded: true, progress: 100, hasCollision: true, walkAllowed: true };
    render(<ViewerPanel scene={buildFixtureScene()} />);
    fireEvent.click(screen.getByRole("button", { name: "3DGS Visual" }));
    expect(await screen.findByTestId("viewer-loaded")).toHaveTextContent("collider trong scene graph");
  });
});
