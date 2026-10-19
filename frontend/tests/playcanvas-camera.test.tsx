import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Entity, EventHandler } from "playcanvas";
import { defaultSettings } from "@playcanvas/supersplat-viewer/settings";

import { PlayCanvasScene, type ViewerControls } from "@/features/viewer/PlayCanvasScene";

const mocks = vi.hoisted(() => ({ createViewer: vi.fn() }));
vi.mock("@playcanvas/supersplat-viewer/viewer", () => ({ createViewer: mocks.createViewer }));

function fixture() {
  const annotations = defaultSettings().annotations;
  const events = new EventHandler();
  const state = {
    loaded: true, progress: 100, cameraMode: "fly", hasCollision: false,
    walkAllowed: false, hasAnimation: false, animationPaused: true,
    animationDuration: 0, animationTime: 0,
  };
  const camera = {
    entity: {
      getPosition: () => ({ x: 1.234567, y: 2, z: 3 }),
      forward: { x: 1, y: 0, z: 0 },
    },
    fov: 85,
  };
  // Only the published ViewerHandle shape: no cameraManager or global property.
  const viewer = {
    app: { root: { findComponent: () => camera }, graphicsDevice: { deviceType: "webgl" } },
    state, events, annotations,
    setCollisionMesh: vi.fn(),
    setCollisionMeshAsync: vi.fn(async () => undefined),
    setCollisionProvider: vi.fn(),
    selectAnnotation: vi.fn(), frameScene: vi.fn(), resetCamera: vi.fn(), seek: vi.fn(), destroy: vi.fn(),
  };
  mocks.createViewer.mockImplementation(async (options) => {
    annotations.push(...options.settings.annotations);
    const root = document.createElement("div");
    root.innerHTML = '<div class="sse-ui"><div class="sse-buttonsContainer"></div></div>';
    options.container.append(root);
    return viewer;
  });
  return viewer;
}

beforeEach(() => { vi.clearAllMocks(); });

describe("PlayCanvas camera bridge", () => {
  it("xoay entity Gaussian và replay bằng cùng quaternion, rồi gỡ listener", async () => {
    const viewer = fixture();
    const appEvents = new EventHandler();
    const splat = new Entity("gsplat", {} as ConstructorParameters<typeof Entity>[1]);
    const on = vi.fn(appEvents.on.bind(appEvents));
    const off = vi.fn(appEvents.off.bind(appEvents));
    Object.assign(viewer.app, { on, off });
    Object.assign(viewer.app.root, { findByName: () => splat });
    const rotation: [number, number, number, number] = [-Math.SQRT1_2, 0, 0, Math.SQRT1_2];
    const cameras = [0, 1].map((x) => ({ center: [x, 2, 3] as [number, number, number], rotation_xyzw: [0, 0, 0, 1] as [number, number, number, number] }));
    const failed = vi.fn();
    const { unmount } = render(<PlayCanvasScene contentUrl="/scene.sog" capability="ready" mode="VISUAL" displayRotation={rotation} cameras={cameras} onFailed={failed} />);
    await waitFor(() => expect(on).toHaveBeenCalledWith("update", expect.any(Function)));
    act(() => { appEvents.fire("update"); });
    const actual = splat.getLocalRotation();
    [actual.x, actual.y, actual.z, actual.w].forEach((value, axis) => expect(value).toBeCloseTo(rotation[axis]));
    const track = mocks.createViewer.mock.calls[0][0].settings.animTracks[0];
    track.keyframes.values.position.slice(0, 3).forEach((value: number, axis: number) => expect(value).toBeCloseTo([0, 3, -2][axis]));
    expect(off).toHaveBeenCalledWith("update", expect.any(Function));
    expect(failed).not.toHaveBeenCalled();
    unmount();
    expect(viewer.destroy).toHaveBeenCalledOnce();
    splat.destroy();
  });

  it("retains the upstream inside environment camera and FOV when no camera was supplied", async () => {
    fixture();
    render(<PlayCanvasScene contentUrl="/scene.sog" capability="ready" mode="VISUAL" onFailed={vi.fn()} />);
    await waitFor(() => expect(mocks.createViewer).toHaveBeenCalled());
    expect(mocks.createViewer.mock.calls[0][0].settings.cameras).toEqual(defaultSettings("environment").cameras);
  });

  it("captures the real app camera and restores poses through the public annotation command", async () => {
    const viewer = fixture();
    let controls: ViewerControls | undefined;
    const pose = { position: [10, 2, 3] as [number, number, number], target: [12, 2, 3] as [number, number, number], fov: 85 };
    const original = { position: [0, 2, 0] as [number, number, number], target: [2, 2, 0] as [number, number, number], fov: 85 };
    const failed = vi.fn();
    const { unmount } = render(<PlayCanvasScene contentUrl="/scene.sog" capability="ready" mode="VISUAL" showControls initialCamera={original} onFailed={failed} onApp={(_app, next) => { controls = next; }} extraControls={<button onClick={() => controls?.gotoPose(pose)}>Restore bookmark</button>} />);
    await waitFor(() => expect(controls).toBeDefined());
    expect(controls!.getCameraPose()).toEqual({ position: [1.234567, 2, 3], target: [3.234567, 2, 3], fov: 85 });
    fireEvent.click(screen.getByRole("button", { name: "Restore bookmark" }));
    expect(viewer.selectAnnotation).toHaveBeenCalledWith(0);
    expect(viewer.annotations[0].camera.initial).toEqual(pose);
    expect(controls!.resetCamera()).toBe(true);
    expect(viewer.state.cameraMode).toBe("orbit");
    expect(viewer.resetCamera).toHaveBeenCalledOnce();
    // Returning home uses the authored reset, not the bookmark navigation slot.
    expect(viewer.selectAnnotation).toHaveBeenCalledTimes(1);
    // A fly button after animation must remain fly; no delayed orbit override.
    await act(async () => {
      controls!.setCameraMode("fly");
      viewer.events.fire("cameraMode:changed", "fly", "anim");
    });
    expect(viewer.state.cameraMode).toBe("fly");
    expect(failed).not.toHaveBeenCalled();
    unmount();
    expect(viewer.destroy).toHaveBeenCalledOnce();
  });

  it("keeps object annotation indices and rejects commands before readiness", async () => {
    const viewer = fixture();
    viewer.state.loaded = false;
    let controls: ViewerControls | undefined;
    const pose = defaultSettings().cameras[0].initial;
    render(<PlayCanvasScene contentUrl="/scene.sog" capability="ready" mode="VISUAL" onFailed={vi.fn()} annotations={[{ position: [0, 0, 0], title: "Object", camera: pose }]} onApp={(_app, next) => { controls = next; }} />);
    await waitFor(() => expect(controls).toBeDefined());
    expect(controls!.getCameraPose()).toBeNull();
    expect(controls!.gotoPose(pose)).toBe(false);
    viewer.state.loaded = true;
    expect(controls!.gotoPose(pose)).toBe(true);
    expect(viewer.annotations[0].title).toBe("Object");
    expect(viewer.selectAnnotation).toHaveBeenLastCalledWith(1);
    controls!.select(0);
    expect(viewer.selectAnnotation).toHaveBeenLastCalledWith(0);
  });
});

it("replaces collision without recreating the viewer or reloading 3DGS and rejects stale loads", async () => {
  const { colliderGlb } = await import("./helpers/collider-glb");
  const viewer = fixture();
  let releaseOld: ((value: object) => void) | undefined;
  const fetcher = vi.fn((url: string) => {
    if (url === "/collision-rev-1.glb") return new Promise((resolve) => { releaseOld = resolve; });
    return Promise.resolve({ ok: true, arrayBuffer: async () => colliderGlb({ frame: "display" }) });
  });
  vi.stubGlobal("fetch", fetcher);
  const failed = vi.fn();
  const collisionError = vi.fn();
  try {
    const { rerender, unmount } = render(<PlayCanvasScene contentUrl="/scene.sog" collisionUrl="/collision-rev-1.glb" capability="ready" mode="VISUAL" onFailed={failed} onCollisionError={collisionError} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith("/collision-rev-1.glb", expect.anything()));
    rerender(<PlayCanvasScene contentUrl="/scene.sog" collisionUrl="/collision-rev-2.glb" capability="ready" mode="VISUAL" onFailed={failed} onCollisionError={collisionError} />);
    await waitFor(() => expect(viewer.setCollisionMeshAsync).toHaveBeenCalledWith(expect.any(Float32Array), expect.any(Uint32Array), expect.any(AbortSignal)));
    expect(viewer.setCollisionMesh.mock.calls.every(([positions]) => positions === null)).toBe(true);
    expect(mocks.createViewer).toHaveBeenCalledTimes(1);
    const count = viewer.setCollisionMeshAsync.mock.calls.length;
    await act(async () => { releaseOld?.({ ok: true, arrayBuffer: async () => colliderGlb() }); });
    expect(viewer.setCollisionMeshAsync).toHaveBeenCalledTimes(count);
    expect(viewer.destroy).not.toHaveBeenCalled();
    expect(failed).not.toHaveBeenCalled();
    unmount();
    expect(viewer.destroy).toHaveBeenCalledOnce();
  } finally { vi.unstubAllGlobals(); }
});

it("shows the backend collision reason and keeps the viewer alive", async () => {
  const viewer = fixture();
  const onCollisionError = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 409, json: async () => ({ detail: "Cần tạo mesh trước khi Walk." }) })));
  try {
    const { unmount } = render(<PlayCanvasScene contentUrl="/scene.sog" collisionUrl="/collision.glb" capability="ready" mode="VISUAL" onFailed={vi.fn()} onCollisionError={onCollisionError} />);
    await waitFor(() => expect(onCollisionError).toHaveBeenCalledWith("Cần tạo mesh trước khi Walk."));
    expect(viewer.destroy).not.toHaveBeenCalled();
    unmount();
  } finally { vi.unstubAllGlobals(); }
});
