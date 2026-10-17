import { describe, expect, it, vi } from "vitest";

interface MockCamera {
  system: {
    app: {
      graphicsDevice: { canvas: HTMLCanvasElement };
    };
  };
}

// Mock TranslateGizmo & RotateGizmo in playcanvas
vi.mock("playcanvas", async (importOriginal) => {
  const actual = await importOriginal<typeof import("playcanvas")>();

  class MockGizmo {
    static createLayer = vi.fn(() => ({ id: 99, name: "Gizmo" }));
    coordSpace = "world";
    enabled = true;
    _device: { canvas: HTMLCanvasElement };
    _onPointerDown = vi.fn();
    _onPointerMove = vi.fn();
    _onPointerUp = vi.fn();
    _getSelection = vi.fn(() => [] as unknown[]);
    private handlers: Record<string, ((...args: unknown[]) => void)[]> = {};

    constructor(camera: MockCamera) {
      this._device = { canvas: camera.system.app.graphicsDevice.canvas };
      this._device.canvas.addEventListener("pointerdown", this._onPointerDown as unknown as EventListener);
      this._device.canvas.addEventListener("pointermove", this._onPointerMove as unknown as EventListener);
      this._device.canvas.addEventListener("pointerup", this._onPointerUp as unknown as EventListener);
    }

    on(event: string, handler: (...args: unknown[]) => void) {
      this.handlers[event] ??= [];
      this.handlers[event].push(handler);
      return this;
    }

    off(event?: string, handler?: (...args: unknown[]) => void) {
      if (!event) this.handlers = {};
      else if (handler) this.handlers[event] = (this.handlers[event] ?? []).filter((h) => h !== handler);
      else delete this.handlers[event];
      return this;
    }

    fire(event: string, ...args: unknown[]) {
      for (const h of this.handlers[event] ?? []) h(...args);
      return this;
    }

    attach = vi.fn();
    detach = vi.fn();
    destroy = vi.fn(() => {
      this._device.canvas.removeEventListener("pointerdown", this._onPointerDown as unknown as EventListener);
      this._device.canvas.removeEventListener("pointermove", this._onPointerMove as unknown as EventListener);
      this._device.canvas.removeEventListener("pointerup", this._onPointerUp as unknown as EventListener);
    });
  }

  return {
    ...actual,
    Gizmo: MockGizmo,
    TranslateGizmo: MockGizmo,
    RotateGizmo: MockGizmo,
  };
});

import { Asset, Entity, Quat, type AppBase } from "playcanvas";

import { SceneOverlay } from "@/features/viewer/scene-overlay";
import type { ViewerAppLike } from "@/features/viewer/PlayCanvasScene";

interface TestGizmo {
  _onPointerDown: ReturnType<typeof vi.fn>;
  _onPointerMove: ReturnType<typeof vi.fn>;
  _onPointerUp: ReturnType<typeof vi.fn>;
  _getSelection: ReturnType<typeof vi.fn>;
}

describe("SceneOverlay - cách ly cử chỉ kéo Gizmo khỏi xoay camera", () => {
  it("gỡ listener bubble mặc định và chặn pointerdown/pointermove ở pha capture khi bấm trúng Gizmo", () => {
    const listeners: Record<string, { handler: EventListener; capture: boolean }[]> = {};
    const canvas = {
      addEventListener: vi.fn((type: string, handler: EventListener, options?: boolean | AddEventListenerOptions) => {
        const capture = typeof options === "boolean" ? options : Boolean(options?.capture);
        listeners[type] ??= [];
        listeners[type].push({ handler, capture });
      }),
      removeEventListener: vi.fn((type: string, handler: EventListener, options?: boolean | EventListenerOptions) => {
        const capture = typeof options === "boolean" ? options : Boolean(options?.capture);
        if (listeners[type]) {
          listeners[type] = listeners[type].filter((l) => l.handler !== handler || l.capture !== capture);
        }
      }),
      hasPointerCapture: vi.fn(() => false),
      releasePointerCapture: vi.fn(),
    } as unknown as HTMLCanvasElement;

    const cameraComponent = {
      entity: {
        getPosition: () => ({ clone: () => ({ x: 0, y: 0, z: 0 }), sub: () => ({ normalize: () => ({}) }) }),
        forward: { x: 0, y: 0, z: -1 },
      },
      farClip: 1000,
      nearClip: 0.1,
      screenToWorld: vi.fn(),
      system: {
        app: {
          graphicsDevice: { canvas },
        },
      },
    };

    const mockApp = {
      root: {
        findComponents: (type: string) => (type === "camera" ? [cameraComponent] : []),
        addChild: vi.fn(),
      },
      graphicsDevice: { canvas },
      renderNextFrame: false,
      scene: {
        layers: {
          insert: vi.fn(),
          layerList: [],
        },
      },
      systems: {
        light: {
          addComponent: vi.fn(),
        },
      },
      assets: {
        add: vi.fn(),
        load: vi.fn(),
        remove: vi.fn(),
      },
    };

    const overlay = new SceneOverlay(mockApp as unknown as ViewerAppLike);

    // Gắn một vật
    overlay.setObjects([
      {
        id: "obj-1",
        url: null,
        position: [0, 0, 0],
        rotation_xyzw: [0, 0, 0, 1],
        visible: true,
      },
    ]);

    const onStart = vi.fn();
    const onEnd = vi.fn();

    overlay.attachGizmo("obj-1", "translate", { onStart, onEnd });

    const overlayAccessor = overlay as unknown as { gizmo: TestGizmo | null };
    const gizmo = overlayAccessor.gizmo;
    expect(gizmo).toBeDefined();
    if (!gizmo) return;

    // Xác nhận listener bubble mặc định của gizmo đã được tháo gỡ khỏi canvas
    const bubbleDown = listeners["pointerdown"]?.filter((l) => !l.capture);
    expect(bubbleDown?.some((l) => l.handler === (gizmo._onPointerDown as unknown as EventListener))).toBe(false);

    // Xác nhận listener pha capture đã được cài đặt
    const captureDown = listeners["pointerdown"]?.find((l) => l.capture);
    const captureMove = listeners["pointermove"]?.find((l) => l.capture);
    const captureUp = listeners["pointerup"]?.find((l) => l.capture);

    expect(captureDown).toBeDefined();
    expect(captureMove).toBeDefined();
    expect(captureUp).toBeDefined();

    // Tình huống 1: Bấm trúng trục Gizmo (_getSelection trả về phần tử)
    gizmo._getSelection.mockReturnValueOnce([{ meshInstance: {} }]);
    const stopImmediatePropagation = vi.fn();
    const preventDefault = vi.fn();

    const hitEvent = {
      target: canvas,
      button: 0,
      pointerId: 42,
      offsetX: 150,
      offsetY: 200,
      stopImmediatePropagation,
      preventDefault,
    } as unknown as PointerEvent;

    captureDown!.handler(hitEvent as unknown as Event);

    // Phải chặn ngay để camera không xoay
    expect(stopImmediatePropagation).toHaveBeenCalledTimes(1);
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(gizmo._onPointerDown).toHaveBeenCalledWith(hitEvent);

    // Tình huống 2: Kéo chuột trong lúc đang drag Gizmo -> camera vẫn không nhận được sự kiện
    const moveStopProp = vi.fn();
    const movePreventDefault = vi.fn();
    const moveEvent = {
      pointerId: 42,
      stopImmediatePropagation: moveStopProp,
      preventDefault: movePreventDefault,
    } as unknown as PointerEvent;

    captureMove!.handler(moveEvent as unknown as Event);
    expect(moveStopProp).toHaveBeenCalledTimes(1);
    expect(gizmo._onPointerMove).toHaveBeenCalledWith(moveEvent);

    // Tình huống 3: Nhả chuột -> kết thúc kéo Gizmo và chặn sự kiện lan sang camera
    const upStopProp = vi.fn();
    const upPreventDefault = vi.fn();
    const upEvent = {
      pointerId: 42,
      stopImmediatePropagation: upStopProp,
      preventDefault: upPreventDefault,
    } as unknown as PointerEvent;

    captureUp!.handler(upEvent as unknown as Event);
    expect(upStopProp).toHaveBeenCalledTimes(1);
    expect(gizmo._onPointerUp).toHaveBeenCalledWith(upEvent);

    // Tình huống 4: Bấm ra ngoài Gizmo (_getSelection rỗng) -> không chặn, cho camera xoay bình thường
    gizmo._getSelection.mockReturnValueOnce([]);
    const missStopProp = vi.fn();
    const missEvent = {
      target: canvas,
      button: 0,
      pointerId: 43,
      offsetX: 50,
      offsetY: 50,
      stopImmediatePropagation: missStopProp,
      preventDefault: vi.fn(),
    } as unknown as PointerEvent;

    captureDown!.handler(missEvent as unknown as Event);
    expect(missStopProp).not.toHaveBeenCalled();
    expect(gizmo._onPointerDown).toHaveBeenCalledTimes(1); // không tăng thêm

    // Tình huống 5: detachGizmo dọn sạch capture listeners
    overlay.detachGizmo();
    expect(overlayAccessor.gizmo).toBeNull();

    const remainingCaptureDown = listeners["pointerdown"]?.filter((l) => l.capture);
    expect(remainingCaptureDown?.length ?? 0).toBe(0);

    overlay.destroy();
  });
});


describe("SceneOverlay - Gaussian and collider attachment", () => {
  it.each(["translate", "rotate"] as const)("%s targets the loaded Gaussian entity and keeps its outline synchronized", (mode) => {
    const canvas = document.createElement("canvas");
    const componentAssets = new Map<Entity, Asset>();
    let overlayRoot: Entity | null = null;
    const app = {
      root: {
        addChild: (entity: Entity) => { sceneRoot.addChild(entity); overlayRoot = entity; },
        findComponents: (type: string) => type === "camera" ? [{ system: { app: { graphicsDevice: { canvas } } } }] : [],
      },
      graphicsDevice: { canvas },
      renderNextFrame: false,
      scene: { layers: { insert: vi.fn(), layerList: [] } },
      systems: {
        light: { addComponent: vi.fn() },
        render: { addComponent: vi.fn() },
        gsplat: { addComponent: (entity: Entity, data: { asset: Asset }) => componentAssets.set(entity, data.asset) },
      },
      assets: {
        add: vi.fn(),
        load: vi.fn((asset: Asset) => {
          asset.resource = { destroy: vi.fn() };
          asset.fire("load", asset);
        }),
        remove: vi.fn(),
      },
    };
    const sceneRoot = new Entity("scene-root", app as unknown as AppBase);
    // AppBase enables its root at startup; this fixture stubs graphics systems, not entity hierarchy.
    (sceneRoot as unknown as { _notifyHierarchyStateChanged(node: Entity, enabled: boolean): void })._notifyHierarchyStateChanged(sceneRoot, true);
    const overlay = new SceneOverlay(app as unknown as ViewerAppLike);
    const input = { id: "candidate-006", url: "/object.ply", position: [1, 2, 3] as [number, number, number], rotation_xyzw: [0, 0, 0, 1] as [number, number, number, number], visible: true };
    overlay.setObjects([input]);
    const child = { translation_xyz: [2, -1, 0.5] as [number, number, number], rotation_quaternion_xyzw: [0, 0, Math.SQRT1_2, Math.SQRT1_2] as [number, number, number, number] };
    const boxes = [{ id: input.id, center: [3, 1, 3.5] as [number,number,number], rotation_xyzw: child.rotation_quaternion_xyzw, dimensions: [1, 2, 3] as [number,number,number], color: "#ff9900", emphasized: false, colliderLocalTransform: child }];
    overlay.setBoxes(boxes);
    overlay.setColliders(boxes, true);
    const root = overlayRoot as unknown as Entity;
    const gaussianEntity = root.findByName(`r2s-object-${input.id}`) as Entity;
    let outline = root.findByName(`r2s-box-${input.id}`) as Entity;
    expect(componentAssets.get(gaussianEntity)?.getFileUrl()).toBe(input.url);
    const handlers = { onStart: vi.fn(), onEnd: vi.fn() };
    overlay.attachGizmo(input.id, mode, handlers);
    const gizmo = (overlay as unknown as { gizmo: { attach: ReturnType<typeof vi.fn>; fire(event: string): void } }).gizmo;
    expect(gizmo.attach).toHaveBeenCalledWith([gaussianEntity]);
    const quaternion = new Quat(0, 0, Math.SQRT1_2, Math.SQRT1_2);
    gaussianEntity.setLocalPosition(7, 8, 9);
    gaussianEntity.setLocalRotation(quaternion);
    gizmo.fire("transform:move");
    outline.getLocalPosition().toArray().forEach((value, axis) => expect(value).toBeCloseTo([8, 10, 9.5][axis], 5));
    outline.getLocalRotation().toArray().forEach((value, axis) => expect(value).toBeCloseTo([0, 0, 1, 0][axis], 5));
    const collider = root.findByName(`r2s-collider-${input.id}`) as Entity;
    collider.getLocalPosition().toArray().forEach((value, axis) => expect(value).toBeCloseTo([8,10,9.5][axis], 5));
    collider.getLocalRotation().toArray().forEach((value, axis) => expect(value).toBeCloseTo([0,0,1,0][axis], 5));
    // Rebuilding layers during a drag must use the live Gaussian pose, not stale authored inputs.
    overlay.setBoxes(boxes);
    overlay.setColliders([...boxes], true);
    for (const name of [`r2s-box-${input.id}`, `r2s-collider-${input.id}`]) {
      const rebuilt = root.findByName(name) as Entity;
      rebuilt.getLocalPosition().toArray().forEach((value, axis) => expect(value).toBeCloseTo([8,10,9.5][axis], 5));
      rebuilt.getLocalRotation().toArray().forEach((value, axis) => expect(value).toBeCloseTo([0,0,1,0][axis], 5));
    }

    outline = root.findByName(`r2s-box-${input.id}`) as Entity;
    overlay.setObjectPose(input.id, [10, 20, 3], [0, 0, Math.SQRT1_2, Math.SQRT1_2]);
    outline.getLocalPosition().toArray().forEach((value, axis) => expect(value).toBeCloseTo([11, 22, 3.5][axis], 5));
    gaussianEntity.setLocalPosition(7, 8, 9);
    gizmo.fire("transform:move");
    gizmo.fire("transform:end");
    expect(handlers.onEnd).toHaveBeenCalledWith(input.id, [7, 8, 9], [0, 0, Math.SQRT1_2, Math.SQRT1_2]);
    const moved = { ...input, position: [7, 8, 9] as [number, number, number], rotation_xyzw: [0, 0, Math.SQRT1_2, Math.SQRT1_2] as [number, number, number, number] };
    overlay.setObjects([{ ...moved, visible: false }]);
    overlay.setBoxes([]);
    expect(gaussianEntity.enabled).toBe(false);
    expect(root.findByName(`r2s-box-${input.id}`)).toBeNull();
    overlay.setObjects([moved]);
    const liveCollider = root.findByName(`r2s-collider-${input.id}`) as Entity;
    overlay.setObjectPose(input.id, [99, 99, 99], [0,0,0,1]);
    overlay.setObjects([input]); // Exit Walk / Reset restores every representation.
    liveCollider.getLocalPosition().toArray().forEach((value, axis) => expect(value).toBeCloseTo([3,1,3.5][axis], 5));
    overlay.setObjects([moved]);
    expect(gaussianEntity.enabled).toBe(true);
    expect(gaussianEntity.getLocalPosition().toArray()).toEqual([7, 8, 9]);
    expect(app.assets.load).toHaveBeenCalledTimes(1);
    overlay.setObjects([]);
    expect(root.findByName(`r2s-object-${input.id}`)).toBeNull();
    expect(app.assets.remove).toHaveBeenCalledWith(componentAssets.get(gaussianEntity));
    expect(app.renderNextFrame).toBe(true);
    overlay.destroy();
  });
});

it("replaces environment assets, rejects late loads, and releases the previous collision entity", async () => {
  const app = {
    graphicsDevice: { canvas: document.createElement("canvas") },
    root: { addChild: vi.fn() },
    systems: { light: { addComponent: vi.fn() }, render: { addComponent: vi.fn() } },
    assets: { add: vi.fn(), load: vi.fn(), remove: vi.fn() },
  };
  const overlay = new SceneOverlay(app as unknown as ViewerAppLike);
  const old = overlay.loadCollision("/old.glb", .3);
  const oldAsset = app.assets.add.mock.lastCall![0] as Asset;
  const current = overlay.loadCollision("/current.glb", .3);
  const currentAsset = app.assets.add.mock.lastCall![0] as Asset;
  expect(app.assets.remove).toHaveBeenCalledWith(oldAsset);
  const entity = new Entity("effective-environment", app as unknown as AppBase);
  currentAsset.resource = { instantiateRenderEntity: () => entity, destroy: vi.fn() };
  currentAsset.fire("load");
  await expect(current).resolves.toBe(0);
  const instantiateStale = vi.fn();
  oldAsset.resource = { instantiateRenderEntity: instantiateStale, destroy: vi.fn() };
  oldAsset.fire("load");
  await expect(old).resolves.toBe(0);
  expect(instantiateStale).not.toHaveBeenCalled();
  const destroy = vi.spyOn(entity, "destroy");
  void overlay.loadCollision("/third.glb", .3);
  expect(destroy).toHaveBeenCalledOnce();
  expect(app.assets.remove).toHaveBeenCalledWith(currentAsset);
  overlay.destroy();
});

it("keeps collider GLB and its live pose when frames are hidden, switches real triangle render styles, and cleans up", async () => {
  const renders: { renderStyle: number; mesh: { generateWireframe: ReturnType<typeof vi.fn> } }[] = [];
  const renderSystem = {
    addComponent(entity: Entity, data: { material: unknown }) {
      const mesh = {
        generateWireframe: vi.fn(), primitive: [{count: 3}],
        getPositions: (out: number[]) => { out.push(0,0,0, 1,0,0, 0,1,0); return 3; },
        getIndices: (out: number[]) => out.push(0,1,2),
      };
      const instance = {mesh, node: entity, material: data.material, renderStyle: 0};
      renders.push(instance);
      (entity as unknown as {c: Record<string, unknown>}).c.render = {meshInstances: [instance], system: renderSystem, onPostStateChange: vi.fn()};
    },
    removeComponent(entity: Entity) { delete (entity as unknown as {c: Record<string, unknown>}).c.render; },
  };
  const app = {
    root: {addChild: vi.fn()}, graphicsDevice: {canvas: document.createElement("canvas")},
    systems: {light: {addComponent: vi.fn()}, render: renderSystem},
    assets: {add: vi.fn(), load: vi.fn(), remove: vi.fn()}, renderNextFrame: false,
  };
  const overlay = new SceneOverlay(app as unknown as ViewerAppLike);
  const makeMesh = () => {
    const entity = new Entity("multipart-child", app as unknown as AppBase);
    entity.setLocalPosition(2,3,4);
    entity.addComponent("render", {type: "box"});
    return entity;
  };
  const boxes = [{id: "A", center: [1,2,3] as [number,number,number], rotation_xyzw: [0,0,0,1] as [number,number,number,number], dimensions: [1,2,3] as [number,number,number], color: "#ffffff", emphasized: true, shapeUrl: "/multipart.glb"}];
  overlay.setBoxes(boxes);
  overlay.setColliders(boxes, true);
  const asset = app.assets.add.mock.lastCall![0] as Asset;
  asset.resource = {instantiateRenderEntity: makeMesh, destroy: vi.fn()};
  asset.fire("load");
  const root = app.root.addChild.mock.lastCall![0] as Entity;
  const collider = root.findByName("r2s-collider-A") as Entity;
  const child = collider.findByName("multipart-child") as Entity;
  expect(child.getLocalPosition().toArray()).toEqual([2,3,4]);
  const selection = root.findByName("r2s-box-A") as Entity;
  expect(selection.findByName("r2s-box-fill-A")).toBeNull();
  expect(selection.children).toHaveLength(2); // Original GLB surface and highlighted edge.
  expect(selection.children[0].getLocalPosition().toArray()).toEqual([2,3,4]);
  const selectionRenders = selection.findComponents("render") as unknown as {meshInstances: {renderStyle: number}[]}[];
  expect(selectionRenders.map((render) => render.meshInstances[0].renderStyle)).toEqual([0,1]);
  overlay.setObjectPose("A", [7,8,9], [0,0,Math.SQRT1_2,Math.SQRT1_2]);
  overlay.setBoxes([]);
  expect(root.findByName("r2s-box-A")).toBeNull();
  expect(root.findByName("r2s-collider-A")).toBe(collider);
  overlay.setColliders(boxes, true, true);
  const instance = renders.at(-1)!;
  expect(instance.renderStyle).toBe(1); // PlayCanvas RENDERSTYLE_WIREFRAME
  expect(instance.mesh.generateWireframe).toHaveBeenCalled();
  expect(collider.getLocalPosition().toArray()).toEqual([7,8,9]);
  overlay.setColliders(boxes, false, false);
  expect(instance.renderStyle).toBe(0); // PlayCanvas RENDERSTYLE_SOLID
  expect(collider.parent!.enabled).toBe(false);
  expect(root.findByName("r2s-collider-A")).toBe(collider);
  const environment = overlay.loadCollision("/effective.glb", .3);
  const environmentAsset = app.assets.add.mock.lastCall![0] as Asset;
  environmentAsset.resource = {instantiateRenderEntity: makeMesh, destroy: vi.fn()};
  environmentAsset.fire("load");
  await expect(environment).resolves.toBe(1);
  overlay.setCollision(true, .3, true);
  expect(renders.at(-1)!.renderStyle).toBe(1);
  overlay.setCollision(true, .3, false);
  expect(renders.at(-1)!.renderStyle).toBe(0);
  const destroyed = vi.spyOn(collider, "destroy");
  const unloaded = vi.spyOn(asset, "unload");
  overlay.destroy();
  expect(destroyed).toHaveBeenCalledOnce();
  expect(unloaded).toHaveBeenCalledOnce();
});
