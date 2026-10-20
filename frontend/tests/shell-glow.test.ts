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
  // The fake app has no scene root; production parents are already in the enabled hierarchy.
  for (const entity of entities.values()) Object.assign(entity, { _enabledInHierarchy: true });
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

  it("chỉ bật vỏ idle khi hover, chuyển vật và rời chuột không nạp lại GLB", async () => {
    const other = new Entity("object-B", app);
    const both = new ShellGlowLayer(hostWith(app, new Map([["A", object], ["B", other]])));
    await both.setShell("A", GLB_URL, "idle");
    await both.setShell("B", GLB_URL, "idle");
    expect(shellOf(object, "A")!.enabled).toBe(false);
    expect(shellOf(other, "B")!.enabled).toBe(false);
    both.setHovered("A");
    expect(shellOf(object, "A")!.enabled).toBe(true);
    both.setHovered("B");
    expect(shellOf(object, "A")!.enabled).toBe(false);
    expect(shellOf(other, "B")!.enabled).toBe(true);
    both.setHovered(null);
    expect(shellOf(other, "B")!.enabled).toBe(false);
    expect(app.assets.load).toHaveBeenCalledTimes(2);
    await both.setShell("A", GLB_URL, "selected");
    both.setHovered("B");
    expect(shellOf(object, "A")!.enabled).toBe(true);
    both.setHovered(null);
    expect(shellOf(object, "A")!.enabled).toBe(true);
    both.destroy();
    expect(() => both.setHovered("A")).not.toThrow();
  });

  it("hover trước khi nạp xong vẫn được giữ; cảnh báo và pending không bị mất khi rời chuột", async () => {
    layer.setHovered("A");
    await layer.setShell("A", GLB_URL, "idle");
    expect(shellOf(object, "A")!.enabled).toBe(true);
    layer.setHovered(null);
    layer.setTone("A", "pending");
    expect(shellOf(object, "A")!.enabled).toBe(true);
    layer.setTone("A", "warning");
    expect(shellOf(object, "A")!.enabled).toBe(true);
    layer.setTone("A", "normal");
    expect(shellOf(object, "A")!.enabled).toBe(false);
  });

  it("vỏ đang chọn có thêm viền, vỏ idle thì không; vật liệu phát sáng cộng dồn và không ghi depth", async () => {
    await layer.setShell("A", GLB_URL, "selected");
    const shell = shellOf(object, "A") as Entity;
    const [solid, wire] = shell.children as Entity[];
    const fill = renderOf(solid).meshInstances[0].material as StandardMaterial;
    expect(fill.opacity).toBeCloseTo(0.2);
    expect(fill.blendType).toBe(BLEND_ADDITIVE);
    expect(fill.depthWrite).toBe(false);
    expect(fill.cull).toBe(CULLFACE_NONE);
    expect(fill.emissive.equals(new Color().fromString("#2dd4bf"))).toBe(true);
    expect((renderOf(wire).meshInstances[0].material as StandardMaterial).opacity).toBeCloseTo(0.4);

    await layer.setShell("A", GLB_URL, "idle");
    const idle = shellOf(object, "A") as Entity;
    expect(idle.children).toHaveLength(1);
    const idleFill = renderOf(idle.children[0] as Entity).meshInstances[0].material as StandardMaterial;
    expect(idleFill.opacity).toBeCloseTo(0.06);
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

describe("ShellGlowLayer: điểm xanh và đỏ", () => {
  let app: AppBase;
  let object: Entity;
  let layer: ShellGlowLayer;

  beforeEach(() => {
    app = fakeApp();
    object = new Entity("object-A", app);
    layer = new ShellGlowLayer(hostWith(app, new Map([["A", object]])));
  });

  const pointsOf = (id: string) => object.children.find((child) => child.name === `r2s-points-${id}`) as Entity | undefined;
  const instanceOf = (child: Entity) => renderOf(child).meshInstances[0];
  const countOf = (instance: MeshInstance) => (instance.mesh as unknown as { positions: number[] }).positions.length / 3;

  it("mỗi loại một mesh điểm: xanh là Gaussian thêm, đỏ là bị loại; số điểm đúng mẫu và vẽ trên cùng", () => {
    layer.setPointSets("A", new Float32Array([0, 0, 0, 1, 1, 1, 2, 2, 2]), new Float32Array([5, 5, 5, 6, 6, 6]));
    const [added, removed] = pointsOf("A")!.children as Entity[];
    const green = instanceOf(added);
    const red = instanceOf(removed);
    expect(countOf(green)).toBe(3);
    expect(countOf(red)).toBe(2);
    expect((green.material as StandardMaterial).emissive.equals(new Color().fromString("#22c55e"))).toBe(true);
    expect((red.material as StandardMaterial).emissive.equals(new Color().fromString("#ef4444"))).toBe(true);
    expect((green.material as StandardMaterial).depthTest).toBe(false);
    expect((red.material as StandardMaterial).depthTest).toBe(false);
  });

  it("điểm là con của entity vật; loại không có mẫu thì không có mesh", () => {
    layer.setPointSets("A", new Float32Array(0), new Float32Array([1, 2, 3]));
    const points = pointsOf("A")!;
    expect(points.parent).toBe(object);
    expect(points.children).toHaveLength(1);
    expect(countOf(instanceOf(points.children[0] as Entity))).toBe(1);
  });

  it("gọi lại thì thay bộ điểm cũ; hai mảng rỗng thì không còn điểm", () => {
    layer.setPointSets("A", new Float32Array(9), new Float32Array(0));
    layer.setPointSets("A", new Float32Array(3), new Float32Array(3));
    expect(object.children.filter((child) => child.name === "r2s-points-A")).toHaveLength(1);
    layer.setPointSets("A", new Float32Array(0), new Float32Array(0));
    expect(pointsOf("A")).toBeUndefined();
  });

  it("clear(id) và destroy gỡ điểm của vật, không để lại entity nào", () => {
    layer.setPointSets("A", new Float32Array([0, 0, 0]), new Float32Array([1, 1, 1]));
    layer.clear("A");
    expect(pointsOf("A")).toBeUndefined();
    layer.setPointSets("A", new Float32Array([0, 0, 0]), new Float32Array(0));
    layer.destroy();
    expect(pointsOf("A")).toBeUndefined();
  });
});

describe("ShellGlowLayer: nhịp phát sáng và trạng thái", () => {
  let app: AppBase;
  let object: Entity;
  let host: SceneOverlay;
  let layer: ShellGlowLayer;

  beforeEach(() => {
    app = fakeApp();
    autoLoad(app);
    object = new Entity("object-A", app);
    host = hostWith(app, new Map([["A", object]]));
    layer = new ShellGlowLayer(host);
    vi.spyOn(Asset.prototype, "unload").mockImplementation(() => undefined);
    window.matchMedia = vi.fn(() => ({ matches: false }) as MediaQueryList);
    vi.spyOn(performance, "now").mockReturnValue(0);
  });

  afterEach(() => {
    Reflect.deleteProperty(window, "matchMedia");
    vi.restoreAllMocks();
  });

  /** Hàm xử lý nhịp khung hình mà lớp đã đăng ký lên viewer. */
  const frame = (): (() => void) => vi.mocked(app.on).mock.calls.find(([event]) => event === "update")![1] as () => void;
  const fillOf = (id: string) => renderOf(shellOf(object, id)!.children[0] as Entity).meshInstances[0].material as StandardMaterial;

  it("vỏ đang chọn nhấp nháy trong 0,19–0,21 và yêu cầu khung kế tiếp; chưa có vỏ thì chưa đăng ký nhịp", async () => {
    expect(app.on).not.toHaveBeenCalled();
    await layer.setShell("A", GLB_URL, "selected");
    expect(app.on).toHaveBeenCalledWith("update", expect.any(Function));
    const fill = fillOf("A");
    let peak = 0;
    for (const now of [0, 500, 1000, 1500, 2000]) {
      vi.mocked(performance.now).mockReturnValue(now);
      frame()();
      expect(fill.opacity).toBeGreaterThanOrEqual(0.19 - 1e-9);
      expect(fill.opacity).toBeLessThanOrEqual(0.21 + 1e-9);
      peak = Math.max(peak, fill.emissiveIntensity);
    }
    expect(peak).toBeGreaterThan(1);
    expect(peak).toBeLessThanOrEqual(1.1 + 1e-9);
    expect(host.requestFrame).toHaveBeenCalled();
  });

  it("vỏ idle không nhấp nháy và không yêu cầu khung", async () => {
    await layer.setShell("A", GLB_URL, "idle");
    vi.mocked(performance.now).mockReturnValue(1000);
    frame()();
    expect(fillOf("A").opacity).toBeCloseTo(0.06);
    expect(host.requestFrame).not.toHaveBeenCalled();
  });

  it("bật giảm chuyển động thì vỏ không nhấp nháy; đang nhấp nháy mà bật thì trả về độ mờ gốc", async () => {
    await layer.setShell("A", GLB_URL, "selected");
    vi.mocked(performance.now).mockReturnValue(1000);
    frame()();
    expect(fillOf("A").opacity).toBeCloseTo(0.21);

    vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList);
    vi.mocked(host.requestFrame).mockClear();
    frame()();
    expect(fillOf("A").opacity).toBeCloseTo(0.2);
    expect(host.requestFrame).not.toHaveBeenCalled();
  });

  it("pending làm mờ vỏ về 0,06 và dừng nhấp nháy; trở lại thường thì có lại độ mờ gốc", async () => {
    await layer.setShell("A", GLB_URL, "selected");
    layer.setTone("A", "pending");
    expect(fillOf("A").opacity).toBeCloseTo(0.06);
    expect((renderOf((shellOf(object, "A") as Entity).children[1] as Entity).meshInstances[0].material as StandardMaterial).opacity).toBeCloseTo(0.06);
    vi.mocked(performance.now).mockReturnValue(1000);
    frame()();
    expect(fillOf("A").opacity).toBeCloseTo(0.06);

    layer.setTone("A", "normal");
    expect(fillOf("A").opacity).toBeCloseTo(0.2);
  });

  it("warning đổi màu vỏ sang cam và giữ độ mờ của kiểu vỏ", async () => {
    await layer.setShell("A", GLB_URL, "selected");
    layer.setTone("A", "warning");
    expect(fillOf("A").emissive.equals(new Color().fromString("#f59e0b"))).toBe(true);
    expect(fillOf("A").opacity).toBeCloseTo(0.2);
  });

  it("setTone khi chưa có vỏ thì không làm gì", () => {
    expect(() => layer.setTone("A", "pending")).not.toThrow();
  });

  it("destroy gỡ đăng ký nhịp khung hình", async () => {
    await layer.setShell("A", GLB_URL, "selected");
    const handler = frame();
    layer.destroy();
    expect(app.off).toHaveBeenCalledWith("update", handler);
  });

  it("nhịp của vỏ đang chọn yêu cầu vẽ tối đa khoảng 10 lần/giây, không vẽ lại cả cảnh mỗi khung (T-064)", async () => {
    await layer.setShell("A", GLB_URL, "selected");
    vi.mocked(host.requestFrame).mockClear();
    for (let now = 0; now < 1000; now += 1000 / 60) {
      vi.mocked(performance.now).mockReturnValue(now);
      frame()();
    }
    expect(vi.mocked(host.requestFrame).mock.calls.length).toBeLessThanOrEqual(11);
    expect(vi.mocked(host.requestFrame).mock.calls.length).toBeGreaterThanOrEqual(5);
  });
});
