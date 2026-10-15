import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

// Mesh cần GPU; tests chỉ cần số đỉnh và cờ wireframe nên dùng bản giả ghi lại dữ liệu.
vi.mock("playcanvas", async (importOriginal) => {
  const actual = await importOriginal<typeof import("playcanvas")>();

  class FakeMesh {
    positions: number[] = [];
    primitive: Record<number, unknown> = {};
    setPositions(values: ArrayLike<number>) {
      this.positions = Array.from(values);
    }
    update() {}
    generateWireframe() {
      this.primitive[actual.RENDERSTYLE_WIREFRAME] = {};
    }
    destroy = vi.fn();
  }

  class FakeMeshInstance {
    mesh: FakeMesh;
    material: unknown;
    renderStyle = 0;
    constructor(mesh: FakeMesh, material: unknown) {
      this.mesh = mesh;
      this.material = material;
    }
  }

  return { ...actual, Mesh: FakeMesh, MeshInstance: FakeMeshInstance };
});

import {
  Asset,
  BLEND_ADDITIVE,
  CULLFACE_NONE,
  Color,
  Entity,
  Mesh,
  MeshInstance,
  StandardMaterial,
  type AppBase,
} from "playcanvas";

import type { SceneOverlay } from "@/features/viewer/scene-overlay";
import { ShellGlowLayer, decodeShellGlb } from "@/features/viewer/shell-glow";

/** Hệ render thật tự gắn/gỡ component trên entity (`entity.c`), như trong test của region-overlay. */
function fakeApp(): AppBase {
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
  return {
    systems: { render: fakeRender },
    on: vi.fn(),
    off: vi.fn(),
    assets: { add: vi.fn(), load: vi.fn(), remove: vi.fn() },
  } as unknown as AppBase;
}

/** Container GLB giả: mỗi lần dựng tạo một entity có một mesh instance, như `instantiateRenderEntity`. */
function fakeContainer(app: AppBase) {
  return {
    instantiateRenderEntity: () => {
      const entity = new Entity("glb", app);
      entity.addComponent("render", { meshInstances: [new MeshInstance(new Mesh(undefined as never), null as never)] });
      return entity;
    },
  };
}

/** Nạp GLB xong ngay khi được yêu cầu, như PlayCanvas nạp một container. */
function autoLoad(app: AppBase): void {
  (app.assets.load as Mock).mockImplementation((asset: Asset) => {
    asset.resource = fakeContainer(app) as never;
    asset.fire("load");
  });
}

function hostWith(app: AppBase, entities: Map<string, Entity>): SceneOverlay {
  return {
    isAlive: () => true,
    application: () => app,
    objectEntity: (id: string) => entities.get(id) ?? null,
    requestFrame: vi.fn(),
  } as unknown as SceneOverlay;
}

const shellOf = (parent: Entity, id: string): Entity | undefined =>
  parent.children.find((child) => child.name === `r2s-shell-${id}`) as Entity | undefined;

const renderOf = (entity: Entity) => (entity as unknown as { c: { render: { meshInstances: MeshInstance[] } } }).c.render;

const GLB_URL = "https://example.test/shell.glb";

describe("ShellGlowLayer: vỏ của vật", () => {
  let app: AppBase;
  let object: Entity;
  let layer: ShellGlowLayer;

  beforeEach(() => {
    app = fakeApp();
    autoLoad(app);
    object = new Entity("object-A", app);
    layer = new ShellGlowLayer(hostWith(app, new Map([["A", object]])));
    URL.createObjectURL = vi.fn(() => "blob:shell");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(Asset.prototype, "unload").mockImplementation(() => undefined);
  });

  afterEach(() => {
    Reflect.deleteProperty(URL, "createObjectURL");
    Reflect.deleteProperty(URL, "revokeObjectURL");
    vi.restoreAllMocks();
  });

  it("vỏ là con của entity vật, nên đi theo transform của vật", async () => {
    await layer.setShell("A", GLB_URL, "idle");
    expect(shellOf(object, "A")?.parent).toBe(object);
  });

  it("vỏ đang chọn có thêm viền, vỏ idle thì không; vật liệu phát sáng cộng dồn và không ghi depth", async () => {
    await layer.setShell("A", GLB_URL, "selected");
    const shell = shellOf(object, "A") as Entity;
    const [solid, wire] = shell.children as Entity[];
    const fill = renderOf(solid).meshInstances[0].material as StandardMaterial;
    expect(fill.opacity).toBeCloseTo(0.25);
    expect(fill.blendType).toBe(BLEND_ADDITIVE);
    expect(fill.depthWrite).toBe(false);
    expect(fill.cull).toBe(CULLFACE_NONE);
    expect(fill.emissive.equals(new Color().fromString("#2dd4bf"))).toBe(true);
    expect((renderOf(wire).meshInstances[0].material as StandardMaterial).opacity).toBeCloseTo(0.5);

    await layer.setShell("A", GLB_URL, "idle");
    const idle = shellOf(object, "A") as Entity;
    expect(idle.children).toHaveLength(1);
    const idleFill = renderOf(idle.children[0] as Entity).meshInstances[0].material as StandardMaterial;
    expect(idleFill.opacity).toBeCloseTo(0.1);
  });

  it("vỏ mới của cùng vật thay vỏ cũ: chỉ còn một vỏ, asset cũ được gỡ và unload", async () => {
    await layer.setShell("A", "https://example.test/first.glb", "idle");
    await layer.setShell("A", "https://example.test/second.glb", "idle");
    expect(object.children.filter((child) => child.name === "r2s-shell-A")).toHaveLength(1);
    expect(app.assets.remove).toHaveBeenCalledTimes(1);
    expect(Asset.prototype.unload).toHaveBeenCalledTimes(1);
  });

  it("GLB dạng ArrayBuffer được nạp qua blob URL rồi thu hồi", async () => {
    await layer.setShell("A", new ArrayBuffer(8), "idle");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    const asset = (app.assets.load as Mock).mock.calls[0][0] as Asset;
    expect((asset.file as { url: string } | null)?.url).toBe("blob:shell");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:shell");
  });

  it("vật chưa có entity trong viewer thì không nạp và không vẽ gì", async () => {
    const empty = new ShellGlowLayer(hostWith(app, new Map()));
    await empty.setShell("missing", GLB_URL, "idle");
    expect(app.assets.load).not.toHaveBeenCalled();
  });

  it("clear(id) chỉ gỡ vỏ của vật đó; destroy gỡ hết, unload asset và không nạp gì nữa", async () => {
    const other = new Entity("object-B", app);
    const both = new ShellGlowLayer(hostWith(app, new Map([["A", object], ["B", other]])));
    await both.setShell("A", GLB_URL, "idle");
    await both.setShell("B", GLB_URL, "idle");
    both.clear("A");
    expect(shellOf(object, "A")).toBeUndefined();
    expect(shellOf(other, "B")).toBeDefined();

    const shell = shellOf(other, "B") as Entity;
    both.destroy();
    both.destroy();
    expect(shell.parent).toBeNull();
    expect(app.assets.remove).toHaveBeenCalledTimes(2);
    expect(Asset.prototype.unload).toHaveBeenCalledTimes(2);
    await both.setShell("B", GLB_URL, "idle");
    expect(app.assets.load).toHaveBeenCalledTimes(2);
  });

  it("decodeShellGlb đổi base64 thành đúng các byte của GLB", () => {
    const bytes = new Uint8Array([103, 108, 84, 70]);
    const base64 = btoa(String.fromCharCode(...bytes));
    expect(new Uint8Array(decodeShellGlb(base64))).toEqual(bytes);
  });
});
