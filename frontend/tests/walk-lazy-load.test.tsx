/** T-065: mở Studio không tải Ammo, lưới va chạm Walk hay collider; bấm Đi bộ mới tải, nạp xong tự vào Walk. */
import { act, fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MetricSceneView } from "@/features/studio/MetricSceneView";
import type { PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";

const renderViewer = vi.hoisted(() => vi.fn());
const loadAmmo = vi.hoisted(() => vi.fn(() => new Promise(() => undefined)));
vi.mock("@/features/viewer/shell-glow", () => ({ ShellGlowLayer: class { destroy = vi.fn(); setShell = vi.fn(); clear = vi.fn(); setHovered = vi.fn(); } }));
vi.mock("@/features/viewer/scene-overlay", () => ({ SceneOverlay: class {
  objectEntity = () => ({}); attachGizmo = vi.fn(); destroy = vi.fn(); detachGizmo = vi.fn(); setObjects = vi.fn(); setBoxes = vi.fn();
  setColliders = vi.fn(); setSurfaceMarkers = vi.fn(); setSplatVisible = vi.fn(); setCollision = vi.fn(); collisionPositions = () => null;
  bindViewerGotoPose = vi.fn(); loadCollision = vi.fn(async () => 0); pickCollisionTriangle = vi.fn(); pick = vi.fn(() => null);
} }));
vi.mock("@/features/viewer/third-person", () => ({ WALK_EYE_HEIGHT_M: 1.3, ThirdPersonRig: class { destroy = vi.fn(); setActive = vi.fn(); setCollision = vi.fn(); } }));
vi.mock("@/features/viewer/scene-physics", async (original) => ({ ...await original<typeof import("@/features/viewer/scene-physics")>(), loadAmmo }));
vi.mock("@/features/viewer/PlayCanvasScene", async (original) => ({
  ...await original<typeof import("@/features/viewer/PlayCanvasScene")>(),
  usePlayCanvasCapability: () => ["ready", vi.fn()],
  PlayCanvasScene: (props: object) => { renderViewer(props); return <div data-testid="viewer-surface" />; },
}));

const visual = { artifact_uri: "artifact://jobs/j/background.sog", artifact_checksum: "sha256:visual" };
const collision = { artifact_uri: "artifact://jobs/j/collision.glb", artifact_checksum: "sha256:mesh" };
const box: PhysicsObjectInput = { id: "A", dynamic: true, position: [0, 0, 1], rotation_xyzw: [0, 0, 0, 1], colliderUrl: null, colliderLocalTransform: null, dimensions: [1, 1, 1], mass_kg: 5, friction: .5, restitution: 0 };
const runtime = { loaded: true, progress: 100, hasCollision: false, walkAllowed: false, cameraMode: "fly", hasAnimation: false, animationPaused: true, animationDuration: 0, animationTime: 0 };

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = vi.fn(() => new Promise<Response>(() => undefined));
});

function walkButton() {
  const controls = render(renderViewer.mock.lastCall![0].extraControls);
  return { button: controls.getByRole("button", { name: "Đi bộ" }), unmount: controls.unmount };
}

describe("walk loads lazily (T-065)", () => {
  it("does not load physics or walk collision until the user asks to walk", async () => {
    const controls = { setObjectCollision: vi.fn(), setCameraMode: vi.fn(() => true) };
    render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={[]} sceneRevision="rev-1" physicsObjects={[box]} />);
    act(() => renderViewer.mock.lastCall![0].onApp({}, controls));
    act(() => renderViewer.mock.lastCall![0].onRuntime(runtime));
    expect(renderViewer.mock.lastCall![0].collisionUrl).toBeNull();
    expect(loadAmmo).not.toHaveBeenCalled();
    expect(global.fetch).not.toHaveBeenCalled();

    const { button, unmount } = walkButton();
    expect(button).toBeEnabled();
    fireEvent.click(button);
    unmount();
    expect(loadAmmo).toHaveBeenCalledOnce();
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("scene_revision=rev-1"), expect.anything());
    const preparing = walkButton();
    expect(preparing.button).toBeDisabled();
    expect(preparing.button).toHaveAttribute("title", "Đang chuẩn bị đi bộ…");
    preparing.unmount();
  });

  it("switches into walk once the collision is ready, without physics objects", () => {
    const controls = { setObjectCollision: vi.fn(), setCameraMode: vi.fn(() => true) };
    render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={[]} sceneRevision="rev-1" />);
    act(() => renderViewer.mock.lastCall![0].onApp({}, controls));
    act(() => renderViewer.mock.lastCall![0].onRuntime(runtime));
    const { button, unmount } = walkButton();
    fireEvent.click(button);
    unmount();
    expect(renderViewer.mock.lastCall![0].collisionUrl).toContain("scene_revision=rev-1");
    act(() => renderViewer.mock.lastCall![0].onRuntime({ ...runtime, hasCollision: true, walkAllowed: true }));
    expect(controls.setCameraMode).toHaveBeenCalledWith("walk");
    expect(() => walkButton()).toThrow();
  });
});
