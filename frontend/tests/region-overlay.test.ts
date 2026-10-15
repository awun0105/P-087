import { describe, expect, it, vi, type Mock } from "vitest";

// Mesh/MeshInstance cần GPU; tests chỉ cần số đỉnh và chỉ số đã nạp, nên dùng bản giả ghi lại dữ liệu.
vi.mock("playcanvas", async (importOriginal) => {
  const actual = await importOriginal<typeof import("playcanvas")>();

  class FakeMesh {
    positions: number[] = [];
    indices: number[] = [];
    setPositions(values: ArrayLike<number>) {
      this.positions = Array.from(values);
    }
    setIndices(values: ArrayLike<number>) {
      this.indices = Array.from(values);
    }
    update() {}
  }

  class FakeMeshInstance {
    mesh: FakeMesh;
    material: unknown;
    constructor(mesh: FakeMesh, material: unknown) {
      this.mesh = mesh;
      this.material = material;
    }
  }

  // Gizmo PlayCanvas: giữ đúng các điểm tiếp xúc mà overlay dùng (attach, enableShape, _shapes, sự kiện transform:*,
  // và _onPointerUp kết thúc cử chỉ như thật, nên huỷ bằng Esc vẫn phát transform:end).
  class FakeGizmo {
    enabled = false;
    coordSpace = "world";
    attached: unknown[] = [];
    _shapes: Record<string, { entity: { enabled: boolean } }> = {
      x: { entity: { enabled: true } },
      y: { entity: { enabled: true } },
      z: { entity: { enabled: true } },
      f: { entity: { enabled: true } },
      xyz: { entity: { enabled: true } },
    };
    _getSelection = vi.fn(() => [] as unknown[]);
    _onPointerDown = vi.fn();
    _onPointerMove = vi.fn();
    _onPointerUp = vi.fn(() => this.fire("transform:end"));
    enableShape = vi.fn();
    attach = vi.fn((nodes: unknown[]) => {
      this.attached = nodes;
      this.enabled = true;
    });
    detach = vi.fn(() => {
      this.enabled = false;
    });
    destroy = vi.fn();
    private handlers: Record<string, Array<() => void>> = {};
    on(event: string, handler: () => void) {
      (this.handlers[event] ??= []).push(handler);
      return this;
    }
    fire(event: string) {
      for (const handler of this.handlers[event] ?? []) handler();
    }
  }
  class FakeRotateGizmo extends FakeGizmo {}
  class FakeTranslateGizmo extends FakeGizmo {}

  return {
    ...actual,
    Mesh: FakeMesh,
    MeshInstance: FakeMeshInstance,
    RotateGizmo: FakeRotateGizmo,
    TranslateGizmo: FakeTranslateGizmo,
  };
});

import {
  Color,
  Entity,
  Quat,
  Vec3 as PcVec3,
  type AppBase,
  type CameraComponent,
  type GraphNode,
  type Layer,
  type StandardMaterial,
} from "playcanvas";

import type { EditableBox, Vec3 } from "@/features/studio/region/box-model";
import {
  RegionOverlay,
  edgeBars,
  handleScale,
  rayLineParam,
  viewPose,
  type RegionHost,
} from "@/features/viewer/region-overlay";
import type { DisplayCameraPose } from "@/features/viewer/source-frame";

const VIEW = { width: 800, height: 600, fovDeg: 60 };

const box = (over: Partial<EditableBox> = {}): EditableBox => ({
  id: "b1",
  op: "add",
  center: [0, 0, 0],
  half: [0.5, 0.5, 0.5],
  yaw: 0,
  ...over,
});

const handlers = () => ({
  onChange: vi.fn<(boxes: EditableBox[]) => void>(),
  onSelect: vi.fn<(id: string | null) => void>(),
});

function fakeApp(canvas: HTMLCanvasElement = document.createElement("canvas")): AppBase {
  // Hệ render thật tự gắn/gỡ component trên entity (`entity.c`) và giữ tham chiếu `system` để destroy().
  const fakeRender = {
    addComponent: (entity: Entity, data: Record<string, unknown>) => {
      const component = { ...data, entity, enabled: true, system: fakeRender, onEnable() {}, onDisable() {}, onPostStateChange() {} };
      (entity as unknown as { c: Record<string, unknown> }).c.render = component;
      return component;
    },
    removeComponent: (entity: Entity) => {
      delete (entity as unknown as { c: Record<string, unknown> }).c.render;
    },
  };
  const app = {
    graphicsDevice: { canvas, clientRect: { width: VIEW.width, height: VIEW.height } },
    systems: { render: fakeRender },
    on: vi.fn(),
    off: vi.fn(),
  } as unknown as AppBase;
  // PlayCanvas bật `app.root` trong hệ phân cấp; entity chỉ "enabled" khi nằm dưới gốc đó.
  const root = new Entity("app-root", app);
  (root as unknown as { _enabledInHierarchy: boolean })._enabledInHierarchy = true;
  (app as unknown as { root: Entity }).root = root;
  return app;
}

function fakeHost(
  app: AppBase,
  object: Entity,
  camera: CameraComponent | null = null,
  gotoPose = vi.fn<(pose: DisplayCameraPose) => boolean>(() => true),
): RegionHost {
  return {
    isAlive: () => true,
    application: () => app,
    activeCamera: () => camera,
    objectEntity: (id: string) => (id === "obj-1" ? object : null),
    sharedGizmoLayer: () => ({}) as Layer,
    requestFrame: vi.fn(),
    gotoPose,
  } as unknown as RegionHost;
}

/**
 * Camera phối cảnh giả: mắt tại `eye`, nhìn về +Y, +X là phải, +Z là lên. `screenToWorld` và `worldToScreen` là hai
 * chiều của cùng một phép chiếu, nên kéo chuột trong test khớp với tia thật của overlay.
 */
function pinholeCamera(app: AppBase, eye: Vec3 = [0, -10, 0]): CameraComponent {
  const focal = VIEW.height / 2 / Math.tan((VIEW.fovDeg * Math.PI) / 360);
  const entity = new Entity("camera", app);
  entity.setPosition(eye[0], eye[1], eye[2]);
  return {
    entity,
    fov: VIEW.fovDeg,
    farClip: 100,
    nearClip: 0.1,
    screenToWorld(x: number, y: number, depth: number) {
      const u = (x - VIEW.width / 2) / focal;
      const v = (VIEW.height / 2 - y) / focal;
      return new PcVec3(eye[0] + depth * u, eye[1] + depth, eye[2] + depth * v);
    },
    worldToScreen(p: PcVec3) {
      const depth = p.y - eye[1];
      return new PcVec3(
        VIEW.width / 2 + (focal * (p.x - eye[0])) / depth,
        VIEW.height / 2 - (focal * (p.z - eye[2])) / depth,
        depth,
      );
    },
  } as unknown as CameraComponent;
}

/** Vật có pose khác đồng nhất: vị trí (1, 2, 3) và quay 90° quanh Z. */
function posedObject(app: AppBase): Entity {
  const object = new Entity("obj-1", app);
  object.setLocalPosition(1, 2, 3);
  object.setLocalRotation(new Quat(0, 0, Math.sin(Math.PI / 4), Math.cos(Math.PI / 4)));
  return object;
}

/** Scene đầy đủ cho test tương tác: vật tại gốc, camera phối cảnh, overlay và các handler giả. */
function scene() {
  const canvas = document.createElement("canvas");
  const app = fakeApp(canvas);
  const object = new Entity("obj-1", app);
  app.root.addChild(object);
  const camera = pinholeCamera(app);
  const callbacks = handlers();
  const gotoPose = vi.fn<(pose: DisplayCameraPose) => boolean>(() => true);
  const overlay = new RegionOverlay(fakeHost(app, object, camera, gotoPose), "obj-1", callbacks);
  return { canvas, app, object, camera, overlay, gotoPose, ...callbacks };
}

/** Toạ độ CSS trên canvas của một điểm object-local (như `offsetX/offsetY` mà trình duyệt báo). */
function screenOf(camera: CameraComponent, p: Vec3): { x: number; y: number } {
  const s = camera.worldToScreen(new PcVec3(p[0], p[1], p[2]));
  return { x: s.x, y: s.y };
}

/** Sự kiện chuột trái trên canvas tại một toạ độ CSS. */
function pointer(canvas: HTMLCanvasElement, type: "pointerdown" | "pointermove" | "pointerup", at: { x: number; y: number }): void {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    offsetX: { value: at.x },
    offsetY: { value: at.y },
    button: { value: 0 },
    pointerId: { value: 1 },
  });
  canvas.dispatchEvent(event);
}

function entityNamed(parent: Entity, name: string): Entity {
  return parent.findByName(name) as Entity;
}

/** Số tay nắm đang gắn dưới box `id`. */
function handleCount(object: Entity, id: string): number {
  return entityNamed(object, `region-box-${id}`).children.filter((child) => child.name.startsWith("region-handle")).length;
}

/** Component render của một node con (lấy từ `findByName`, nên nhận `GraphNode`). */
function renderOf(node: GraphNode): { material: StandardMaterial; meshInstances: { mesh: { positions: number[]; indices: number[] } }[] } {
  return (node as Entity).findComponents("render")[0] as unknown as {
    material: StandardMaterial;
    meshInstances: { mesh: { positions: number[]; indices: number[] } }[];
  };
}

function expectColor(actual: Color, hex: string): void {
  const expected = new Color().fromString(hex);
  expect(actual.r).toBeCloseTo(expected.r, 6);
  expect(actual.g).toBeCloseTo(expected.g, 6);
  expect(actual.b).toBeCloseTo(expected.b, 6);
}

describe("edgeBars", () => {
  it("builds twelve solid bars for a solid outline", () => {
    expect(edgeBars([0.5, 0.5, 0.5], false, 0.01).indices.length).toBe(12 * 36);
  });

  it("splits every edge into dashes for a subtract outline", () => {
    const solid = edgeBars([0.5, 0.5, 0.5], false, 0.01);
    const dashed = edgeBars([0.5, 0.5, 0.5], true, 0.01);
    expect(dashed.indices.length).toBeGreaterThan(solid.indices.length);
  });
});

describe("rayLineParam", () => {
  it("returns the line parameter where a ray crosses the line", () => {
    expect(rayLineParam([0, -10, 0], [0.6, 10, 0], [0.5, 0, 0], [1, 0, 0])).toBeCloseTo(0.1, 9);
  });

  it("returns null for a ray parallel to the line", () => {
    expect(rayLineParam([0, 0, 1], [1, 0, 0], [0, 0, 0], [1, 0, 0])).toBeNull();
  });
});

describe("handleScale", () => {
  it("keeps the handle about 14 pixels wide at any distance", () => {
    for (const distance of [2, 10, 40]) {
      const metersPerPixel = (2 * distance * Math.tan(Math.PI / 6)) / 600;
      expect(handleScale(distance, 60, 600) / metersPerPixel).toBeCloseTo(14, 9);
    }
  });
});

describe("RegionOverlay.setBoxes", () => {
  it("draws one entity per box under the region root", () => {
    const app = fakeApp();
    const object = new Entity("obj-1", app);
    const overlay = new RegionOverlay(fakeHost(app, object), "obj-1", handlers());
    overlay.setBoxes([box({ id: "a" }), box({ id: "b", op: "subtract" })], null);
    expect(object.findByName("r2s-region")?.children.length).toBe(2);
  });

  it("places each box at its object-local centre under a posed object", () => {
    const app = fakeApp();
    const object = posedObject(app);
    const overlay = new RegionOverlay(fakeHost(app, object), "obj-1", handlers());
    overlay.setBoxes([box({ center: [0.5, 0, 0] })], null);
    const world = object.findByName("region-box-b1")!.getPosition();
    expect(world.x).toBeCloseTo(1, 9);
    expect(world.y).toBeCloseTo(2.5, 9);
    expect(world.z).toBeCloseTo(3, 9);
  });

  it("colours add boxes green and subtract boxes red", () => {
    const app = fakeApp();
    const object = new Entity("obj-1", app);
    const overlay = new RegionOverlay(fakeHost(app, object), "obj-1", handlers());
    overlay.setBoxes([box({ id: "a" }), box({ id: "b", op: "subtract" })], null);
    expectColor(renderOf(object.findByName("region-faces-a")!).material.emissive, "#22c55e");
    expectColor(renderOf(object.findByName("region-faces-b")!).material.emissive, "#ef4444");
  });

  it("draws the faces at the full box size", () => {
    const app = fakeApp();
    const object = new Entity("obj-1", app);
    const overlay = new RegionOverlay(fakeHost(app, object), "obj-1", handlers());
    overlay.setBoxes([box({ half: [1, 0.5, 2] })], null);
    const scale = object.findByName("region-faces-b1")!.getLocalScale();
    expect([scale.x, scale.y, scale.z]).toEqual([2, 1, 4]);
  });

  it("dashes the subtract outline and thickens the selected box's outline", () => {
    const app = fakeApp();
    const object = new Entity("obj-1", app);
    const overlay = new RegionOverlay(fakeHost(app, object), "obj-1", handlers());
    const reach = (id: string) => {
      const positions = renderOf(object.findByName(`region-edges-${id}`)!).meshInstances[0].mesh.positions;
      return Math.max(...positions.filter((_, i) => i % 3 === 0).map(Math.abs));
    };
    const indexCount = (id: string) => renderOf(object.findByName(`region-edges-${id}`)!).meshInstances[0].mesh.indices.length;

    overlay.setBoxes([box({ id: "add" }), box({ id: "sub", op: "subtract" })], "add");
    expect(indexCount("sub")).toBeGreaterThan(indexCount("add"));
    const selectedReach = reach("add");

    overlay.setBoxes([box({ id: "add" }), box({ id: "sub", op: "subtract" })], null);
    expect(selectedReach).toBeGreaterThan(reach("add"));
  });
});

describe("RegionOverlay face handles, drag and pick", () => {
  it("shows six handles on the selected box only", () => {
    const { object, overlay } = scene();
    overlay.setBoxes([box({ id: "a" }), box({ id: "b", center: [2, 0, 0] })], "a");
    expect(handleCount(object, "a")).toBe(6);
    expect(handleCount(object, "b")).toBe(0);
  });

  it("sizes the handles to about 14 pixels from the camera", () => {
    const { object, overlay } = scene();
    overlay.setBoxes([box()], "b1");
    const handle = entityNamed(object, "region-box-b1").children.find((c) => c.name.startsWith("region-handle")) as Entity;
    // Camera ở (0, -10, 0), tâm box cách 10 m.
    expect(handle.getLocalScale().x).toBeCloseTo(handleScale(10, VIEW.fovDeg, VIEW.height), 9);
  });

  it("drags the +x face by the pointer distance and reports the box only on release", () => {
    const { canvas, camera, overlay, onChange } = scene();
    overlay.setBoxes([box()], "b1");
    pointer(canvas, "pointerdown", screenOf(camera, [0.5, 0, 0]));
    pointer(canvas, "pointermove", screenOf(camera, [0.55, 0, 0]));
    expect(onChange).not.toHaveBeenCalled();
    pointer(canvas, "pointermove", screenOf(camera, [0.6, 0, 0]));
    pointer(canvas, "pointerup", screenOf(camera, [0.6, 0, 0]));
    expect(onChange).toHaveBeenCalledTimes(1);
    const [boxes] = onChange.mock.calls[0];
    expect(boxes[0].half[0]).toBeCloseTo(0.55, 6);
    expect(boxes[0].center[0]).toBeCloseTo(0.05, 6);
    expect(boxes[0].center[0] - boxes[0].half[0]).toBeCloseTo(-0.5, 6);
  });

  it("keeps pointer moves away from the camera while a face is dragged", () => {
    const { canvas, camera, overlay } = scene();
    overlay.setBoxes([box()], "b1");
    const cameraSees = vi.fn();
    canvas.addEventListener("pointermove", cameraSees);
    pointer(canvas, "pointerdown", screenOf(camera, [0.5, 0, 0]));
    pointer(canvas, "pointermove", screenOf(camera, [0.6, 0, 0]));
    expect(cameraSees).not.toHaveBeenCalled();
    pointer(canvas, "pointerup", screenOf(camera, [0.6, 0, 0]));
    pointer(canvas, "pointermove", screenOf(camera, [0.7, 0, 0]));
    expect(cameraSees).toHaveBeenCalledTimes(1);
  });

  it("cancels a drag on Escape, restores the box and gives pointer moves back to the camera", () => {
    const { canvas, camera, overlay, object, onChange } = scene();
    overlay.setBoxes([box()], "b1");
    const cameraSees = vi.fn();
    canvas.addEventListener("pointermove", cameraSees);
    pointer(canvas, "pointerdown", screenOf(camera, [0.5, 0, 0]));
    pointer(canvas, "pointermove", screenOf(camera, [0.6, 0, 0]));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    pointer(canvas, "pointermove", screenOf(camera, [0.7, 0, 0]));
    pointer(canvas, "pointerup", screenOf(camera, [0.7, 0, 0]));
    expect(onChange).not.toHaveBeenCalled();
    expect(cameraSees).toHaveBeenCalledTimes(1);
    expect(entityNamed(object, "region-faces-b1").getLocalScale().x).toBeCloseTo(1, 9);
  });

  it("selects the box under the pointer and moves the handles to it", () => {
    const { canvas, camera, overlay, object, onSelect } = scene();
    overlay.setBoxes([box({ id: "a" }), box({ id: "b", center: [2, 3, 0] })], "a");
    pointer(canvas, "pointerdown", screenOf(camera, [2, 3, 0]));
    expect(onSelect).toHaveBeenCalledWith("b");
    expect(handleCount(object, "b")).toBe(6);
    expect(handleCount(object, "a")).toBe(0);
  });
});

/** Các điểm của gizmo fake mà test dùng. */
interface FakeGizmoLike {
  enabled: boolean;
  coordSpace: string;
  attached: unknown[];
  enableShape: Mock;
  _shapes: Record<string, { entity: { enabled: boolean } }>;
  _getSelection: Mock;
  _onPointerMove: Mock;
  fire(event: string): void;
}

function gizmosOf(overlay: RegionOverlay): { rotateGizmo: FakeGizmoLike; translateGizmo: FakeGizmoLike } {
  return overlay as unknown as { rotateGizmo: FakeGizmoLike; translateGizmo: FakeGizmoLike };
}

const yawQuat = (yaw: number) => new Quat(0, 0, Math.sin(yaw / 2), Math.cos(yaw / 2));

describe("RegionOverlay gizmos", () => {
  it("attaches the rotate and translate gizmos to the selected box in local space", () => {
    const { overlay } = scene();
    overlay.setBoxes([box({ id: "a" }), box({ id: "b", center: [2, 0, 0] })], "b");
    const { rotateGizmo, translateGizmo } = gizmosOf(overlay);
    expect(rotateGizmo.coordSpace).toBe("local");
    expect(translateGizmo.coordSpace).toBe("local");
    expect((rotateGizmo.attached[0] as Entity).name).toBe("region-box-b");
    expect((translateGizmo.attached[0] as Entity).name).toBe("region-box-b");

    overlay.setBoxes([box({ id: "a" }), box({ id: "b", center: [2, 0, 0] })], "a");
    expect((rotateGizmo.attached[0] as Entity).name).toBe("region-box-a");
  });

  it("limits the rotate gizmo to the Z ring and hides the other rings", () => {
    const { overlay } = scene();
    overlay.setBoxes([box()], "b1");
    const { rotateGizmo } = gizmosOf(overlay);
    // Tên công khai của PlayCanvas cho vòng mặt là "face"; trong _shapes vòng đó nằm ở khoá "f".
    for (const [publicAxis, shape] of [
      ["x", "x"],
      ["y", "y"],
      ["face", "f"],
      ["xyz", "xyz"],
    ]) {
      expect(rotateGizmo.enableShape).toHaveBeenCalledWith(publicAxis, false);
      expect(rotateGizmo._shapes[shape].entity.enabled).toBe(false);
    }
    expect(rotateGizmo.enableShape).not.toHaveBeenCalledWith("z", false);
  });

  it("rotates the box about its centre on release and reports the new yaw", () => {
    const { object, overlay, onChange } = scene();
    overlay.setBoxes([box()], "b1");
    const { rotateGizmo } = gizmosOf(overlay);
    rotateGizmo.fire("transform:start");
    entityNamed(object, "region-box-b1").setLocalRotation(yawQuat(Math.PI / 6));
    rotateGizmo.fire("transform:move");
    expect(onChange).not.toHaveBeenCalled();
    rotateGizmo.fire("transform:end");
    expect(onChange).toHaveBeenCalledTimes(1);
    const [boxes] = onChange.mock.calls[0];
    expect(boxes[0].yaw).toBeCloseTo(Math.PI / 6, 9);
    expect(boxes[0].center).toEqual([0, 0, 0]);
  });

  it("moves the box centre on release of the translate gizmo", () => {
    const { object, overlay, onChange } = scene();
    overlay.setBoxes([box()], "b1");
    const { translateGizmo } = gizmosOf(overlay);
    translateGizmo.fire("transform:start");
    entityNamed(object, "region-box-b1").setLocalPosition(0.4, 0.1, 0);
    translateGizmo.fire("transform:end");
    expect(onChange).toHaveBeenCalledTimes(1);
    const [boxes] = onChange.mock.calls[0];
    expect(boxes[0].center[0]).toBeCloseTo(0.4, 9);
    expect(boxes[0].center[1]).toBeCloseTo(0.1, 9);
  });

  it("keeps pointer moves away from the camera during a gizmo drag", () => {
    const { canvas, overlay } = scene();
    overlay.setBoxes([box()], "b1");
    const { translateGizmo } = gizmosOf(overlay);
    const cameraSees = vi.fn();
    canvas.addEventListener("pointermove", cameraSees);
    translateGizmo._getSelection.mockReturnValue([{}]);
    pointer(canvas, "pointerdown", { x: 1, y: 1 });
    pointer(canvas, "pointermove", { x: 2, y: 2 });
    expect(cameraSees).not.toHaveBeenCalled();
    expect(translateGizmo._onPointerMove).toHaveBeenCalled();
  });

  it("keeps the bottom on the floor after a face drag pushes it below on release", () => {
    const { canvas, camera, overlay, onChange } = scene();
    overlay.setFloorZ(0);
    // Đáy box cách sàn 10 cm; tay nắm -z nằm ở đáy và được kéo xuống 20 cm, xuống dưới sàn.
    overlay.setBoxes([box({ center: [0, 0, 0.6] })], "b1");
    pointer(canvas, "pointerdown", screenOf(camera, [0, 0, 0.1]));
    pointer(canvas, "pointermove", screenOf(camera, [0, 0, -0.1]));
    pointer(canvas, "pointerup", screenOf(camera, [0, 0, -0.1]));
    expect(onChange).toHaveBeenCalledTimes(1);
    const [[boxes]] = onChange.mock.calls;
    // Đỉnh giữ nguyên ở 1.1 m, đáy bám sàn.
    expect(boxes[0].center[2] - boxes[0].half[2]).toBeCloseTo(0, 6);
    expect(boxes[0].center[2] + boxes[0].half[2]).toBeCloseTo(1.1, 6);
  });

  it("keeps the top fixed when a translate drops the bottom under the floor", () => {
    const { object, overlay, onChange } = scene();
    overlay.setFloorZ(0);
    overlay.setBoxes([box({ center: [0, 0, 0.5] })], "b1");
    const { translateGizmo } = gizmosOf(overlay);
    translateGizmo.fire("transform:start");
    entityNamed(object, "region-box-b1").setLocalPosition(0, 0, 0.2);
    translateGizmo.fire("transform:end");
    const [[boxes]] = onChange.mock.calls;
    expect(boxes[0].center[2] - boxes[0].half[2]).toBeCloseTo(0, 6);
    expect(boxes[0].center[2] + boxes[0].half[2]).toBeCloseTo(0.7, 6);
  });

  it("leaves the bottom where it was dragged when no floor has been set", () => {
    const { canvas, camera, overlay, onChange } = scene();
    overlay.setBoxes([box({ center: [0, 0, 0.5] })], "b1");
    pointer(canvas, "pointerdown", screenOf(camera, [0, 0, 0]));
    pointer(canvas, "pointermove", screenOf(camera, [0, 0, -0.2]));
    pointer(canvas, "pointerup", screenOf(camera, [0, 0, -0.2]));
    const [[boxes]] = onChange.mock.calls;
    expect(boxes[0].center[2] - boxes[0].half[2]).toBeCloseTo(-0.2, 6);
  });

  it("cancels a gizmo drag on Escape, restores the box and reports nothing", () => {
    const { canvas, object, overlay, onChange } = scene();
    overlay.setBoxes([box()], "b1");
    const { translateGizmo } = gizmosOf(overlay);
    translateGizmo._getSelection.mockReturnValue([{}]);
    pointer(canvas, "pointerdown", { x: 1, y: 1 });
    translateGizmo.fire("transform:start");
    entityNamed(object, "region-box-b1").setLocalPosition(0.6, 0, 0);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(entityNamed(object, "region-box-b1").getLocalPosition().x).toBeCloseTo(0, 9);
  });
});

describe("viewPose", () => {
  const IDENTITY = { x: [1, 0, 0] as Vec3, y: [0, 1, 0] as Vec3, z: [0, 0, 1] as Vec3 };

  it("looks down -Z from above for the top view, framing the sphere with 20 % margin", () => {
    // Bán kính 1 m, FOV 60°: khoảng cách = 1.2 / sin(30°) = 2.4 m.
    const pose = viewPose("top", [0, 0, 0], IDENTITY, 1, 60);
    expect(pose.position[0]).toBeCloseTo(0, 9);
    expect(pose.position[1]).toBeCloseTo(0, 9);
    expect(pose.position[2]).toBeCloseTo(2.4, 9);
    expect(pose.target).toEqual([0, 0, 0]);
    expect(pose.fov).toBe(60);
  });

  it("views the front along +Y and the side along +X from the negative side", () => {
    expect(viewPose("front", [0, 0, 0], IDENTITY, 1, 60).position[1]).toBeCloseTo(-2.4, 9);
    expect(viewPose("side", [0, 0, 0], IDENTITY, 1, 60).position[0]).toBeCloseTo(-2.4, 9);
  });
});

describe("RegionOverlay.viewFrom", () => {
  it("frames the selected box from the chosen preset and hands the pose to the viewer", () => {
    const { overlay, gotoPose } = scene();
    overlay.setBoxes([box()], "b1");
    expect(overlay.viewFrom("front")).toBe(true);
    // Half-diagonal 0.866 m: khoảng cách = 1.2 · 0.866 / sin(30°) ≈ 2.078 m, nhìn theo +Y từ phía -Y.
    const [pose] = gotoPose.mock.calls[0];
    expect(pose.position[1]).toBeCloseTo(-2.0785, 3);
    expect(pose.target).toEqual([0, 0, 0]);
  });

  it("aims along the box's own axes when the box is rotated", () => {
    const { overlay, gotoPose } = scene();
    overlay.setBoxes([box({ yaw: Math.PI / 2 })], "b1");
    // Trục x của box quay về +Y thế giới, nên nhìn theo +X của box là nhìn từ phía -Y.
    overlay.viewFrom("side");
    const [pose] = gotoPose.mock.calls[0];
    expect(pose.position[0]).toBeCloseTo(0, 6);
    expect(pose.position[1]).toBeCloseTo(-2.0785, 3);
  });

  it("returns false and reports nothing when no box is selected", () => {
    const { overlay, gotoPose } = scene();
    overlay.setBoxes([box()], null);
    expect(overlay.viewFrom("top")).toBe(false);
    expect(gotoPose).not.toHaveBeenCalled();
  });

  it("returns false when the viewer refuses the pose", () => {
    const { overlay, gotoPose } = scene();
    gotoPose.mockReturnValueOnce(false);
    overlay.setBoxes([box()], "b1");
    expect(overlay.viewFrom("top")).toBe(false);
  });
});
