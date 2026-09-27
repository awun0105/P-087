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
