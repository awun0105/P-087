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

import { Color, Entity, Quat, type AppBase, type GraphNode, type Layer, type StandardMaterial } from "playcanvas";

import type { EditableBox } from "@/features/studio/region/box-model";
import { RegionOverlay, edgeBars, type RegionHost, type RegionOverlayHandlers } from "@/features/viewer/region-overlay";

const box = (over: Partial<EditableBox> = {}): EditableBox => ({
  id: "b1",
  op: "add",
  center: [0, 0, 0],
  half: [0.5, 0.5, 0.5],
  yaw: 0,
  ...over,
});

const handlers = (): RegionOverlayHandlers => ({ onChange: vi.fn(), onSelect: vi.fn() });

function fakeApp(): AppBase {
  const canvas = document.createElement("canvas");
  // Hệ render thật tự gắn/gỡ component trên entity (`entity.c`) và giữ tham chiếu `system` để destroy().
  const fakeRender = {
    addComponent: (entity: Entity, data: Record<string, unknown>) => {
      const component = { ...data, entity, enabled: true, system: fakeRender };
      (entity as unknown as { c: Record<string, unknown> }).c.render = component;
      return component;
    },
    removeComponent: (entity: Entity) => {
      delete (entity as unknown as { c: Record<string, unknown> }).c.render;
    },
  };
  return {
    graphicsDevice: { canvas },
    systems: { render: fakeRender },
    on: vi.fn(),
    off: vi.fn(),
  } as unknown as AppBase;
}

function fakeHost(app: AppBase, object: Entity): RegionHost {
  return {
    isAlive: () => true,
    application: () => app,
    activeCamera: () => null,
    objectEntity: (id: string) => (id === "obj-1" ? object : null),
    sharedGizmoLayer: () => ({}) as Layer,
    requestFrame: vi.fn(),
    gotoPose: vi.fn(() => true),
  } as unknown as RegionHost;
}

/** Vật có pose khác đồng nhất: vị trí (1, 2, 3) và quay 90° quanh Z. */
function posedObject(app: AppBase): Entity {
  const object = new Entity("obj-1", app);
  object.setLocalPosition(1, 2, 3);
  object.setLocalRotation(new Quat(0, 0, Math.sin(Math.PI / 4), Math.cos(Math.PI / 4)));
  return object;
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
