import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import type { PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";

const renderViewer = vi.hoisted(() => vi.fn());
const gizmo = vi.hoisted(() => vi.fn());
vi.mock("@/features/viewer/scene-overlay", () => ({ SceneOverlay: class {
  attachGizmo = gizmo;
  destroy = vi.fn(); detachGizmo = vi.fn(); setObjects = vi.fn(); setBoxes = vi.fn();
  setSplatVisible = vi.fn(); setCollision = vi.fn(); collisionPositions = () => null;
  loadCollision = async () => 0;
} }));
vi.mock("@/features/viewer/third-person", () => ({
  WALK_EYE_HEIGHT_M: 1.3, ThirdPersonRig: class {
    destroy = vi.fn(); setActive = vi.fn(); setCollision = vi.fn();
  },
}));
vi.mock("@/features/viewer/PlayCanvasScene", async (original) => ({
  ...await original<typeof import("@/features/viewer/PlayCanvasScene")>(),
  usePlayCanvasCapability: () => ["ready", vi.fn()],
  PlayCanvasScene: (props: object) => { renderViewer(props); return <div />; },
}));
const visual = { artifact_uri: "artifact://jobs/j/background.sog", artifact_checksum: "sha256:visual" };
const collision = { artifact_uri: "artifact://jobs/j/collision.glb", artifact_checksum: "sha256:mesh" };
const cameras: [] = [];

describe("MetricSceneView effective collision", () => {
  it("changes revision collision URL while preserving the reconstruction content URL", () => {
    const { rerender } = render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-1" />);
    const before = renderViewer.mock.lastCall![0];
    expect(before.collisionUrl).toContain("scene_revision=rev-1");
    rerender(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-2" />);
    const after = renderViewer.mock.lastCall![0];
    expect(after.collisionUrl).toContain("scene_revision=rev-2");
    expect(after.contentUrl).toBe(before.contentUrl);
  });

  it("does not silently omit a confirmed static collider after removing its source region", () => {
    const object: PhysicsObjectInput = { id: "static-A", dynamic: false, position: [7, 8, 9], rotation_xyzw: [0, 0, 0, 1], colliderUrl: null, colliderLocalTransform: null, dimensions: [1, 2, 3], mass_kg: 0, friction: .5, restitution: 0 };
    render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-3" physicsObjects={[object]} />);
    expect(screen.queryByText(/BLOCKED BY PR-04/)).not.toBeInTheDocument();
    expect(renderViewer.mock.lastCall![0].collisionUrl).toBeNull();
  });
});


it("leaves Walk before gizmo editing to prevent live physics from replacing the edited pose", async () => {
  const controls = { setCameraMode: vi.fn(), setInputEnabled: vi.fn() };
  const objects = [{ id: "A", url: null, position: [0,0,1] as [number,number,number], rotation_xyzw: [0,0,0,1] as [number,number,number,number], visible: true }];
  render(<MetricSceneView jobId="j" visual={visual} cameras={cameras} objects={objects} gizmo={{id:"A",mode:"translate"}} />);
  act(() => renderViewer.mock.lastCall![0].onApp({}, controls));
  await waitFor(() => expect(gizmo).toHaveBeenCalled());
  act(() => gizmo.mock.lastCall![2].onStart());
  expect(controls.setCameraMode).toHaveBeenLastCalledWith("fly");
  expect(controls.setInputEnabled).toHaveBeenLastCalledWith(false);
});
