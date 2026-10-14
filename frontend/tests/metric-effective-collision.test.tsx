import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import type { PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";

const renderViewer = vi.hoisted(() => vi.fn());
const gizmo = vi.hoisted(() => vi.fn());
const setBoxes = vi.hoisted(() => vi.fn());
const setColliders = vi.hoisted(() => vi.fn());
const setCollision = vi.hoisted(() => vi.fn());
const loadCollision = vi.hoisted(() => vi.fn<(url: string, opacity: number) => Promise<number>>(async () => 0));
const pickCollisionTriangle = vi.hoisted(() => vi.fn());
vi.mock("@/features/viewer/scene-overlay", () => ({ SceneOverlay: class {
  attachGizmo = gizmo;
  destroy = vi.fn(); detachGizmo = vi.fn(); setObjects = vi.fn(); setBoxes = setBoxes; setColliders = setColliders; setSurfaceMarkers = vi.fn();
  setSplatVisible = vi.fn(); setCollision = setCollision; collisionPositions = () => null;
  loadCollision = loadCollision; pickCollisionTriangle = pickCollisionTriangle;
} }));
vi.mock("@/features/viewer/third-person", () => ({
  WALK_EYE_HEIGHT_M: 1.3, ThirdPersonRig: class {
    destroy = vi.fn(); setActive = vi.fn(); setCollision = vi.fn();
  },
}));
vi.mock("@/features/viewer/PlayCanvasScene", async (original) => ({
  ...await original<typeof import("@/features/viewer/PlayCanvasScene")>(),
  usePlayCanvasCapability: () => ["ready", vi.fn()],
  PlayCanvasScene: (props: object) => { renderViewer(props); return <div data-testid="viewer-surface" />; },
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
  const controls = { setCameraMode: vi.fn(), setInputEnabled: vi.fn(), setObjectCollision: vi.fn() };
  const objects = [{ id: "A", url: null, position: [0,0,1] as [number,number,number], rotation_xyzw: [0,0,0,1] as [number,number,number,number], visible: true }];
  render(<MetricSceneView jobId="j" visual={visual} cameras={cameras} objects={objects} gizmo={{id:"A",mode:"translate"}} />);
  act(() => renderViewer.mock.lastCall![0].onApp({}, controls));
  await waitFor(() => expect(gizmo).toHaveBeenCalled());
  act(() => gizmo.mock.lastCall![2].onStart());
  expect(controls.setCameraMode).toHaveBeenLastCalledWith("fly");
  expect(controls.setInputEnabled).toHaveBeenLastCalledWith(false);
});

it("separates selection frames from active collider geometry and toggles triangle edges", () => {
  const object: PhysicsObjectInput = { id: "A", dynamic: false, position: [7, 8, 9], rotation_xyzw: [0, 0, Math.SQRT1_2, Math.SQRT1_2], colliderUrl: "/parts.glb", colliderLocalTransform: { translation_xyz: [2, -1, .5], rotation_quaternion_xyzw: [0, 0, 0, 1] }, dimensions: [1, 2, 3], mass_kg: null, friction: .5, restitution: 0 };
  const boxes = [{id: "A", center: [8, 10, 9.5] as [number, number, number], rotation_xyzw: object.rotation_xyzw, dimensions: [1,2,3] as [number,number,number], color: "#ffffff", emphasized: false}];
  render(<MetricSceneView jobId="j" visual={visual} cameras={cameras} boxes={boxes} physicsObjects={[object]} />);
  act(() => renderViewer.mock.lastCall![0].onApp({}, {setObjectCollision: vi.fn()}));
  fireEvent.click(screen.getByLabelText("Collision mesh"));
  const colliders = setColliders.mock.lastCall![0];
  expect(colliders[0].center).toEqual([8,10,9.5]);
  expect(colliders[0].shapeUrl).toBe("/parts.glb");
  expect(setColliders.mock.lastCall!.slice(1)).toEqual([true,false]);
  fireEvent.click(screen.getByLabelText("Khung vật thể"));
  expect(setBoxes).toHaveBeenLastCalledWith([]);
  expect(setColliders.mock.lastCall![0]).toBe(colliders);
  expect(setColliders.mock.lastCall!.slice(1)).toEqual([true,false]);
  fireEvent.click(screen.getByLabelText("Cạnh tam giác mesh"));
  expect(setColliders.mock.lastCall!.slice(1)).toEqual([true,true]);
  expect(setCollision).toHaveBeenLastCalledWith(true,.3,true);
  fireEvent.click(screen.getByLabelText("Collision mesh"));
  expect(setColliders.mock.lastCall!.slice(1)).toEqual([false,true]);
});

it("does not rebuild live object layers when environment load finishes or mesh display options change", async () => {
  let finish!: (triangles: number) => void;
  loadCollision.mockImplementationOnce(() => new Promise<number>((resolve) => {finish = resolve;}));
  const boxes = [{id: "A", center: [0,0,1] as [number,number,number], rotation_xyzw: [0,0,0,1] as [number,number,number,number], dimensions: [1,2,3] as [number,number,number], color: "#ffffff", emphasized: false}];
  render(<MetricSceneView jobId="j" visual={visual} collision={collision} sceneRevision="rev-1" cameras={cameras} boxes={boxes} />);
  act(() => renderViewer.mock.lastCall![0].onApp({}, {setObjectCollision: vi.fn()}));
  setBoxes.mockClear(); setColliders.mockClear();
  await act(async () => finish(100));
  expect(setBoxes).not.toHaveBeenCalled();
  expect(setColliders).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("Collision mesh"));
  fireEvent.click(screen.getByLabelText("Cạnh tam giác mesh"));
  expect(setBoxes).not.toHaveBeenCalled();
});

it("uses preview URLs and sends a picked canonical triangle to surface annotation and infill controls", () => {
  const onMarkSurface=vi.fn(), onRemoveSurface=vi.fn(),onFillSurface=vi.fn();
  render(<MetricSceneView jobId="j" visual={visual} collision={collision} sceneRevision="rev-1" collisionPreview cameras={cameras} onMarkSurface={onMarkSurface} onRemoveSurface={onRemoveSurface} onFillSurface={onFillSurface} surfacePlanes={[{id:"plane-1",kind:"floor",source_checksum:"sha256:mesh",points:[[0,0,0],[1,0,0],[0,1,0]]}]} />);
  act(()=>renderViewer.mock.lastCall![0].onApp({}, {setObjectCollision:vi.fn(),setCameraMode:vi.fn()}));
  expect(renderViewer.mock.lastCall![0].collisionUrl).toContain("preview=true");
  expect(loadCollision.mock.lastCall![0]).toContain("preview=true");
  const points=[[0,0,0],[1,0,0],[0,1,0]];
  pickCollisionTriangle.mockReturnValue(points);
  fireEvent.click(screen.getByRole("button",{name:"Đánh dấu sàn"}));
  const canvas=document.createElement("canvas");
  screen.getByTestId("viewer-surface").appendChild(canvas);
  fireEvent.pointerDown(canvas,{clientX:20,clientY:20});
  fireEvent.pointerUp(canvas,{clientX:20,clientY:20});
  expect(onMarkSurface).toHaveBeenCalledWith("floor",points);
  fireEvent.click(screen.getByRole("button",{name:"Lấp theo mặt phẳng sàn 1"}));
  expect(onFillSurface).toHaveBeenCalledWith("plane-1");
  fireEvent.click(screen.getByRole("button",{name:"Xóa mặt phẳng sàn 1"}));
  expect(onRemoveSurface).toHaveBeenCalledWith("plane-1");
});

it("reports the active collision source, revision, triangle count and selected convex parts", async () => {
  loadCollision.mockResolvedValueOnce(123);
  render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-5"
    collisionDiagnostics={{source: "Object-aware", backgroundChecksum: "sha256:active-background", selectedParts: 3}} />);
  act(() => renderViewer.mock.lastCall![0].onApp({}, {setObjectCollision: vi.fn()}));
  fireEvent.click(screen.getByLabelText("Collision mesh"));
  await waitFor(() => expect(screen.getByLabelText("Thông tin collision")).toHaveTextContent("Tam giác môi trường: 123"));
  const diagnostics = screen.getByLabelText("Thông tin collision");
  expect(diagnostics).toHaveTextContent("Nguồn: Object-aware");
  expect(diagnostics).toHaveTextContent("Revision: rev-5");
  expect(diagnostics).toHaveTextContent("Khối lồi của vật đang chọn: 3");
  expect(diagnostics).toHaveTextContent("sha256:active-background");
});
