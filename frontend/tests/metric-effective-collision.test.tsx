import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import type { PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";
import { EMPTY_INSPECTION } from "@/features/viewer/inspection-history";
import type { CollisionSurfacePlane } from "@/lib/api/studio";

const setShell = vi.hoisted(() => vi.fn(async () => undefined));
const clearShell = vi.hoisted(() => vi.fn());
const setHovered = vi.hoisted(() => vi.fn());
// T-070: viewer dùng SOG gốc ngay (không hỏi bộ LOD) trong test này.
vi.mock("@/features/viewer/useLodView", async () => {
  const { jobArtifactContentUrl } = await import("@/lib/api/endpoints");
  return { useLodView: (jobId: string, ref: { artifact_uri: string; artifact_checksum: string }) => ({ url: jobArtifactContentUrl(jobId, ref), filename: ref.artifact_uri.split("/").pop(), lod: false, settled: true }) };
});
vi.mock("@/features/viewer/shell-glow", () => ({ ShellGlowLayer: class {
  destroy = vi.fn(); setShell = setShell; clear = clearShell; setHovered = setHovered;
} }));
const renderViewer = vi.hoisted(() => vi.fn());
const gizmo = vi.hoisted(() => vi.fn());
const setBoxes = vi.hoisted(() => vi.fn());
const setColliders = vi.hoisted(() => vi.fn());
const setCollision = vi.hoisted(() => vi.fn());
const loadCollision = vi.hoisted(() => vi.fn<(url: string, opacity: number) => Promise<number>>(async () => 0));
const pickCollisionTriangle = vi.hoisted(() => vi.fn());
const pick = vi.hoisted(() => vi.fn<() => string | null>(() => "A"));
vi.mock("@/features/viewer/scene-overlay", () => ({ SceneOverlay: class { prioritizeObject = vi.fn();
  objectEntity = () => ({}); attachGizmo = gizmo;
  destroy = vi.fn(); detachGizmo = vi.fn(); setObjects = vi.fn(); setBoxes = setBoxes; setColliders = setColliders; setSurfaceMarkers = vi.fn();
  setSplatVisible = vi.fn(); setCollision = setCollision; collisionPositions = () => null; bindViewerGotoPose = vi.fn();
  loadCollision = loadCollision; pickCollisionTriangle = pickCollisionTriangle; pick = pick;
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

/** T-065: lưới va chạm Walk chỉ nạp sau khi bấm Đi bộ. */
function askWalk() {
  act(() => renderViewer.mock.lastCall![0].onRuntime({ loaded: true, progress: 100, hasCollision: false, walkAllowed: false, cameraMode: "fly", hasAnimation: false, animationPaused: true, animationDuration: 0, animationTime: 0 }));
  const controls = render(renderViewer.mock.lastCall![0].extraControls);
  fireEvent.click(controls.getByRole("button", { name: "Đi bộ" }));
  controls.unmount();
}

it("hover chỉ làm sáng vật dưới chuột; kéo camera, rời canvas và chọn điểm thì tắt", () => {
  const props = { jobId: "j", visual, cameras, shells: [{ id: "A", url: "/shell.glb", style: "idle" as const }], onPickBox: vi.fn(), inspection: { onReady: vi.fn(), onState: vi.fn() } };
  const { rerender } = render(<MetricSceneView {...props} />);
  act(() => renderViewer.mock.lastCall![0].onApp({}, { setObjectCollision: vi.fn() }));
  const surface = screen.getByTestId("viewer-surface");
  const canvas = document.createElement("canvas");
  surface.append(canvas);
  pick.mockReturnValue("A");
  const move = (buttons = 0) => fireEvent(canvas, new MouseEvent("pointermove", { bubbles: true, clientX: 20, clientY: 30, buttons }));
  move();
  expect(setHovered).toHaveBeenLastCalledWith("A");
  expect(props.onPickBox).not.toHaveBeenCalled();
  pick.mockReturnValue(null);
  move();
  expect(setHovered).toHaveBeenLastCalledWith(null);
  pick.mockReturnValue("A");
  move(1);
  expect(setHovered).toHaveBeenLastCalledWith(null);
  move();
  expect(setHovered).toHaveBeenLastCalledWith("A");
  fireEvent.pointerLeave(surface.parentElement!);
  expect(setHovered).toHaveBeenLastCalledWith(null);
  move();
  act(() => renderViewer.mock.lastCall![0].onInspectionState({ ...EMPTY_INSPECTION, measuring: true }));
  expect(setHovered).toHaveBeenLastCalledWith(null);
  move();
  expect(setHovered).toHaveBeenLastCalledWith(null);
  act(() => renderViewer.mock.lastCall![0].onInspectionState(EMPTY_INSPECTION));
  rerender(<MetricSceneView {...props} selectMode={false} />);
  move();
  expect(setHovered).toHaveBeenLastCalledWith(null);
});

describe("MetricSceneView effective collision", () => {
  it("requests the original reconstruction collision explicitly for a stage preview", () => {
    render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} reconstruction />);
    askWalk();
    const url = renderViewer.mock.lastCall![0].collisionUrl;
    expect(url).toContain("reconstruction=true");
    expect(url).not.toContain("scene_revision");
  });
  it("changes revision collision URL while preserving the reconstruction content URL", () => {
    const { rerender } = render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-1" />);
    askWalk();
    const before = renderViewer.mock.lastCall![0];
    expect(before.collisionUrl).toContain("scene_revision=rev-1");
    rerender(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-2" />);
    const after = renderViewer.mock.lastCall![0];
    expect(after.collisionUrl).toContain("scene_revision=rev-2");
    expect(after.contentUrl).toBe(before.contentUrl);
  });

  it("does not reload an invisible collision overlay after a pose save; enables it for the current revision", () => {
    loadCollision.mockClear();
    const props = { jobId: "j", visual, collision, cameras };
    const { rerender } = render(<MetricSceneView {...props} sceneRevision="rev-1" />);
    act(() => renderViewer.mock.lastCall![0].onApp({}, { setObjectCollision: vi.fn() }));
    expect(loadCollision).not.toHaveBeenCalled();
    rerender(<MetricSceneView {...props} sceneRevision="rev-2" />);
    expect(loadCollision).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Collision mesh"));
    expect(loadCollision).toHaveBeenCalledOnce();
    expect(loadCollision.mock.lastCall![0]).toContain("scene_revision=rev-2");
    fireEvent.click(screen.getByLabelText("Collision mesh"));
    rerender(<MetricSceneView {...props} sceneRevision="rev-3" />);
    expect(loadCollision).toHaveBeenCalledOnce();
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
  render(<MetricSceneView jobId="j" visual={visual} collision={collision} sceneRevision="rev-1" cameras={cameras} boxes={boxes} defaultLayers={{ splat: true, collision: true, boxes: true }} />);
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
  const panel = render(<div data-testid="surface-tools" />).getByTestId("surface-tools");
  render(<MetricSceneView surfaceToolsTarget={panel} jobId="j" visual={visual} collision={collision} sceneRevision="rev-1" collisionPreview cameras={cameras} onMarkSurface={onMarkSurface} onRemoveSurface={onRemoveSurface} onFillSurface={onFillSurface} surfacePlanes={[{id:"plane-1",kind:"floor",source_checksum:"sha256:mesh",points:[[0,0,0],[1,0,0],[0,1,0]]}]} />);
  act(()=>renderViewer.mock.lastCall![0].onApp({}, {setObjectCollision:vi.fn(),setCameraMode:vi.fn()}));
  askWalk();
  expect(within(screen.getByLabelText("Chọn layer hiển thị")).queryByRole("button", {name: "Đánh dấu sàn"})).toBeNull();
  expect(within(panel).getByRole("button", {name: "Đánh dấu sàn"})).toBeInTheDocument();
  expect(renderViewer.mock.lastCall![0].collisionUrl).toContain("preview=true");
  const points=[[0,0,0],[1,0,0],[0,1,0]];
  pickCollisionTriangle.mockReturnValue(points);
  fireEvent.click(screen.getByRole("button",{name:"Đánh dấu sàn"}));
  expect(loadCollision.mock.lastCall![0]).toContain("preview=true");
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

it("loads collision without showing preview and diagnostic banners", async () => {
  loadCollision.mockResolvedValueOnce(123);
  render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-5" collisionPreview
    collisionDiagnostics={{source: "Object-aware", backgroundChecksum: "sha256:active-background", selectedParts: 3}} />);
  act(() => renderViewer.mock.lastCall![0].onApp({}, {setObjectCollision: vi.fn()}));
  fireEvent.click(screen.getByLabelText("Collision mesh"));
  await waitFor(() => expect(loadCollision).toHaveBeenCalled());
  expect(screen.queryByLabelText("Thông tin collision")).toBeNull();
  expect(screen.queryByText(/Walk kiểm tra bố trí hiện tại/)).toBeNull();
});

describe("MetricSceneView khoá Draft (T-013)", () => {
  it("khoá Đi bộ: không nạp lưới va chạm và có nút Đi bộ bị khoá kèm lý do", () => {
    render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-1" lockedReason="Cần tạo mesh trước" />);
    const props = renderViewer.mock.lastCall![0];
    expect(props.collisionUrl).toBeNull();
    const controls = render(props.extraControls);
    const walk = controls.getByRole("button", { name: "Đi bộ" });
    expect(walk).toBeDisabled();
    expect(walk).toHaveAttribute("title", "Cần tạo mesh trước");
  });

  it("ngoài Draft thì nút Đi bộ bấm được và bấm mới nạp lưới va chạm (T-065)", () => {
    render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} sceneRevision="rev-1" />);
    expect(renderViewer.mock.lastCall![0].collisionUrl).toBeNull();
    askWalk();
    expect(renderViewer.mock.lastCall![0].collisionUrl).toContain("scene_revision=rev-1");
  });

  it("khoá Dịch và Xoay của vật đang chọn, không mở gizmo", () => {
    render(
      <MetricSceneView
        jobId="j"
        visual={visual}
        cameras={cameras}
        sceneRevision="rev-1"
        selectedObject={{ id: "A", name: "Pallet", viewportHidden: false, canTransform: true }}
        tool="none"
        onTool={vi.fn()}
        lockedReason="Cần tạo mesh trước"
      />,
    );
    for (const name of ["Dịch", "Xoay"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Cần tạo mesh trước");
    }
  });

  it("khoá Nhân bản và các nút mặt va chạm trong Draft; scene sẵn sàng vẫn bấm được", () => {
    const surfacePlanes = [{ id: "surface-1", kind: "floor", points: [[0, 0, 0], [1, 0, 0], [0, 1, 0]], fill_regions: false }] as CollisionSurfacePlane[];
    const panel = render(<div data-testid="surface-tools" />).getByTestId("surface-tools");
    const props = {
      surfaceToolsTarget: panel,
      jobId: "j",
      visual,
      cameras,
      sceneRevision: "rev-1",
      selectedObject: { id: "A", name: "Pallet", viewportHidden: false, canTransform: true },
      surfacePlanes,
      onMarkSurface: vi.fn(),
      onRemoveSurface: vi.fn(),
      onFillSurface: vi.fn(),
      onDuplicate: vi.fn(),
    };
    const controlNames = ["Nhân bản", "Đánh dấu sàn", "Đánh dấu tường", "Xóa mặt phẳng sàn 1", "Lấp theo mặt phẳng sàn 1"];

    const { unmount } = render(<MetricSceneView {...props} lockedReason="Cần tạo mesh trước" />);
    for (const name of controlNames) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "Nhân bản" })).toHaveAttribute("title", "Cần tạo mesh trước");
    unmount();

    render(<MetricSceneView {...props} />);
    for (const name of controlNames) {
      expect(screen.getByRole("button", { name })).toBeEnabled();
    }
  });
});


it("hides collision and selection boxes while Benchmark picks splat points, then restores layer choices", () => {
  const onState = vi.fn();
  const boxes = [{id: "A", center: [0,0,1] as [number,number,number], rotation_xyzw: [0,0,0,1] as [number,number,number,number], dimensions: [1,2,3] as [number,number,number], color: "#ffffff", emphasized: false}];
  render(<MetricSceneView jobId="j" visual={visual} collision={collision} cameras={cameras} objects={[{id: "A", url: null, visible: true, position: [0,0,1], rotation_xyzw: [0,0,0,1]}]} shells={[{id: "A", url: "/shell.glb", style: "selected"}]} boxes={boxes} inspection={{onReady: vi.fn(), onState}} />);
  act(() => renderViewer.mock.lastCall![0].onApp({}, {setObjectCollision: vi.fn()}));
  fireEvent.click(screen.getByLabelText("Collision mesh"));
  expect(setBoxes).toHaveBeenLastCalledWith(boxes);
  const reportInspection = renderViewer.mock.lastCall![0].onInspectionState;
  act(() => reportInspection({...EMPTY_INSPECTION, measuring: true}));
  expect(renderViewer.mock.lastCall![0].onInspectionState).toBe(reportInspection);
  expect(setCollision).toHaveBeenLastCalledWith(false, .3, false);
  expect(setColliders.mock.lastCall![1]).toBe(false);
  expect(setBoxes).toHaveBeenLastCalledWith([]);
  expect(clearShell).toHaveBeenCalledWith("A");
  setShell.mockClear();
  expect(onState).toHaveBeenLastCalledWith({...EMPTY_INSPECTION, measuring: true});
  act(() => renderViewer.mock.lastCall![0].onInspectionState(EMPTY_INSPECTION));
  expect(setCollision).toHaveBeenLastCalledWith(true, .3, false);
  expect(setShell).toHaveBeenCalledWith("A", "/shell.glb", "selected");
  expect(setBoxes).toHaveBeenLastCalledWith(boxes);
});

it("cancels triangle picking when the surface tools tab closes", () => {
  const panel = render(<div data-testid="surface-tools" />).getByTestId("surface-tools");
  const props = {jobId: "j", visual, cameras, surfaceToolsTarget: panel, onMarkSurface: vi.fn()};
  const {rerender} = render(<MetricSceneView {...props} surfaceToolsActive />);
  fireEvent.click(within(panel).getByRole("button", {name: "Đánh dấu sàn"}));
  expect(within(panel).getByRole("button", {name: "Đánh dấu sàn"})).toHaveAttribute("aria-pressed", "true");
  rerender(<MetricSceneView {...props} surfaceToolsActive={false} />);
  expect(within(panel).getByRole("button", {name: "Đánh dấu sàn"})).toHaveAttribute("aria-pressed", "false");
  expect(within(panel).queryByRole("button", {name: "Hủy đánh dấu"})).toBeNull();
});
