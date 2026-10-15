import { describe, expect, it, vi } from "vitest";

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

  return { ...actual, Mesh: FakeMesh, MeshInstance: FakeMeshInstance };
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
  type RegionHost,
} from "@/features/viewer/region-overlay";

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

function fakeHost(app: AppBase, object: Entity, camera: CameraComponent | null = null): RegionHost {
  return {
    isAlive: () => true,
    application: () => app,
    activeCamera: () => camera,
    objectEntity: (id: string) => (id === "obj-1" ? object : null),
    sharedGizmoLayer: () => ({}) as Layer,
    requestFrame: vi.fn(),
    gotoPose: vi.fn(() => true),
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
  const overlay = new RegionOverlay(fakeHost(app, object, camera), "obj-1", callbacks);
  return { canvas, app, object, camera, overlay, ...callbacks };
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
