/** T-064: Studio ẩn (đổi tab hoặc tab trình duyệt ẩn) → viewer thoát Walk và ngừng cập nhật; hiện lại → chạy tiếp, vẽ một khung. */
import { act, render, waitFor } from "@testing-library/react";
import { EventHandler } from "playcanvas";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlayCanvasScene } from "@/features/viewer/PlayCanvasScene";
import { ViewerActiveContext } from "@/features/viewer/viewerActive";

const mocks = vi.hoisted(() => ({ createViewer: vi.fn() }));
vi.mock("@playcanvas/supersplat-viewer/viewer", () => ({ createViewer: mocks.createViewer }));

function fixture() {
  const viewer = {
    app: { root: { findComponent: () => null }, graphicsDevice: { deviceType: "webgl" }, timeScale: 1, renderNextFrame: false },
    state: { loaded: true, progress: 100, cameraMode: "walk", hasCollision: true, walkAllowed: true, hasAnimation: false, animationPaused: true, animationDuration: 0, animationTime: 0 },
    events: new EventHandler(), annotations: [],
    setCollisionMesh: vi.fn(), setCollisionMeshAsync: vi.fn(async () => undefined), setCollisionProvider: vi.fn(),
    selectAnnotation: vi.fn(), frameScene: vi.fn(), resetCamera: vi.fn(), seek: vi.fn(), destroy: vi.fn(),
  };
  mocks.createViewer.mockResolvedValue(viewer);
  return viewer;
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => setVisibility("visible"));

const scene = (active: boolean) => (
  <ViewerActiveContext.Provider value={active}>
    <PlayCanvasScene contentUrl="/scene.sog" capability="ready" mode="VISUAL" onFailed={vi.fn()} />
  </ViewerActiveContext.Provider>
);

describe("hidden Studio suspends the viewer (T-064)", () => {
  it("exits walk and stops updates when the Studio tab is left, then resumes", async () => {
    const viewer = fixture();
    const view = render(scene(true));
    await waitFor(() => expect(mocks.createViewer).toHaveBeenCalled());
    await waitFor(() => expect(viewer.app.timeScale).toBe(1));
    view.rerender(scene(false));
    await waitFor(() => expect(viewer.app.timeScale).toBe(0));
    expect(viewer.state.cameraMode).toBe("fly");
    view.rerender(scene(true));
    await waitFor(() => expect(viewer.app.timeScale).toBe(1));
    expect(viewer.app.renderNextFrame).toBe(true);
  });

  it("pauses while the browser tab is hidden", async () => {
    const viewer = fixture();
    viewer.state.cameraMode = "orbit";
    render(scene(true));
    await waitFor(() => expect(mocks.createViewer).toHaveBeenCalled());
    act(() => setVisibility("hidden"));
    await waitFor(() => expect(viewer.app.timeScale).toBe(0));
    expect(viewer.state.cameraMode).toBe("orbit");
    act(() => setVisibility("visible"));
    await waitFor(() => expect(viewer.app.timeScale).toBe(1));
  });
});
