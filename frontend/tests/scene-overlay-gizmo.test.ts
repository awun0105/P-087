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
