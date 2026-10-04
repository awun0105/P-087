"use client";

/**
 * Visual 3DGS của viewer, render bằng `@playcanvas/supersplat-viewer`.
 *
 * Căn cứ: `INTEGRATION_PLAYBOOK:745` và `PRODUCT-06.md` §13.1. Ba điều phải nói
 * rõ vì chúng quyết định hành vi thật:
 *
 * 1. **Ưu tiên WebGPU, fallback WebGL2 theo API upstream.** Có tùy chọn ép WebGL
 *    khi cần chẩn đoán. Backend thật đọc từ graphicsDevice, không đoán từ cấu hình.
 * 2. **Collider đi qua `collisionUrl` của chính viewer**, nên collider GLB nằm trong
 *    cùng `pc.AppBase` với SOG — đây là phần Single Scene Graph mà
 *    `TRACK.md:39` yêu cầu, và là lý do không tự dựng mesh trong engine thứ hai.
 *    Lớp kỹ thuật còn lại vẫn do `SceneCanvas` lo; xem `PRODUCT-06.md` §13.1.
 * 3. **Trạng thái load/camera đọc từ `viewer.state`**, không tự bịa thanh tiến trình:
 *    `state.progress` là 0..100 và `state.loaded` chỉ true sau frame đầu.
 *
 * Canonical SceneIR transforms thuộc `layers.ts`. Raw preview giữ đơn vị SfM;
 * inspection chỉ inverse transform hiển thị để trả điểm về hệ nguồn, không
 * xác nhận metric hoặc sửa canonical state qua PlayCanvas.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import type { ViewMode } from "@/features/viewer/layers";
import { DISPLAY_EULER, type DisplayCameraPose, type SourceFrame } from "@/features/viewer/source-frame";
import type { SplatInspection } from "./splat-inspection";
import { EMPTY_INSPECTION, type InspectionState } from "./inspection-history";

import "@playcanvas/supersplat-viewer/viewer.css";

/** Runtime capability của browser, đo trước khi gọi createViewer để tránh throw. */
export type PlayCanvasCapability = "unknown" | "ready" | "unavailable" | "failed";

/** Trạng thái runtime lấy từ `ViewerHandle.state` của thư viện, không phải tự đếm. */
export interface PlayCanvasRuntime {
  loaded: boolean;
  progress: number;
  hasCollision: boolean;
  walkAllowed: boolean;
  /** Bộ điều khiển camera đang chạy trong viewer (đọc từ `state.cameraMode`). */
  cameraMode: CameraMode;
  graphicsBackend?: string;
}

/** Chế độ camera của supersplat-viewer; `anim` là hoạt ảnh camera dựng sẵn (Studio không dùng). */
export type CameraMode = "orbit" | "fly" | "walk" | "anim";

export const INITIAL_RUNTIME: PlayCanvasRuntime = {
  loaded: false,
  progress: 0,
  hasCollision: false,
  walkAllowed: false,
  cameraMode: "orbit",
};

/**
 * Sự kiện con lăn với bước cuộn nhân hệ số. Tốc độ zoom của viewer là hằng số nội bộ
 * (`wheelSpeed`), không có trong settings, nên host nhân bước cuộn trước khi viewer nhận.
 */
export function scaledWheelInit(event: WheelEvent, factor: number): WheelEventInit {
  return {
    deltaX: event.deltaX * factor,
    deltaY: event.deltaY * factor,
    deltaZ: event.deltaZ * factor,
    deltaMode: event.deltaMode,
    clientX: event.clientX,
    clientY: event.clientY,
    screenX: event.screenX,
    screenY: event.screenY,
    ctrlKey: event.ctrlKey,
    shiftKey: event.shiftKey,
    altKey: event.altKey,
    metaKey: event.metaKey,
    buttons: event.buttons,
    bubbles: true,
    cancelable: true,
    composed: true,
  };
}

export function detectPlayCanvasCapability(): PlayCanvasCapability {
  if (typeof document === "undefined") {
    return "unknown";
  }
  const canvas = document.createElement("canvas");
  const hasWebGpu = typeof navigator !== "undefined" && "gpu" in navigator;
  try {
    const gl = canvas.getContext("webgl2");
    gl?.getExtension?.("WEBGL_lose_context")?.loseContext();
    return gl || hasWebGpu ? "ready" : "unavailable";
  } catch {
    return hasWebGpu ? "ready" : "unavailable";
  }
}

const subscribeCapability = () => () => undefined;
const serverCapability = (): PlayCanvasCapability => "unknown";

/** SSR/hydration cùng snapshot unknown; chỉ probe GPU ở client, một lần mỗi host. */
export function usePlayCanvasCapability() {
  const cache = useRef<PlayCanvasCapability | null>(null);
  const read = useCallback(() => {
    cache.current ??= detectPlayCanvasCapability();
    return cache.current;
  }, []);
  const detected = useSyncExternalStore(subscribeCapability, read, serverCapability);
  const [override, setOverride] = useState<PlayCanvasCapability | null>(null);
  return [override ?? detected, setOverride] as const;
}

export interface PlayCanvasSceneProps {
  /** URL của SOG đã resolve qua artifact endpoint; null nghĩa là chưa có Visual. */
  contentUrl: string | null;
  renderer?: "webgpu" | "webgl";
  /** File preview cục bộ; object URL có cùng lifecycle với engine. */
  contentFile?: File;
  /** Bắt buộc với blob URL: parser chọn format theo tên gốc, không theo UUID. */
  contentFilename?: string;
  /** Preview file độc lập dùng controls upstream; job viewer dùng toolbar riêng. */
  showControls?: boolean;
  /** Collider GLB của cùng scene, để viewer nạp trong cùng app. */
  collisionUrl?: string | null;
  mode: ViewMode;
  /** Đo một lần ở host, để degraded state của cả viewer chỉ có một nguồn sự thật. */
  capability: PlayCanvasCapability;
  onFailed: () => void;
  onRuntime?: (runtime: PlayCanvasRuntime) => void;
  enableInspection?: boolean;
  /** Số điểm tối đa của một bộ chọn (2 = đo A/B, 5 = xác nhận tỉ lệ mét). */
  inspectionMaxPoints?: number;
  onInspectionReady?: (controller: SplatInspection | null) => void;
  onInspectionState?: (state: InspectionState) => void;
  /** Hệ trục của nội dung; mặc định `colmap` (output Brush). Artifact hệ mét REC-06 là `z_up`. */
  sourceFrame?: SourceFrame;
  /** Camera khởi đầu trong không gian hiển thị (vd camera quay đầu tiên); caller memo hoá. */
  initialCamera?: DisplayCameraPose;
  /**
   * Điểm đến của camera (không gian hiển thị), khai lúc tạo viewer; `ViewerControls.select(i)` bay
   * tới điểm thứ i bằng transition của viewer. Hotspot mặc định bị ẩn: host tự vẽ danh sách.
   * Caller memo hoá theo nội dung, vì đổi mảng này sẽ tạo lại viewer.
   */
  annotations?: readonly ViewerAnnotation[];
  /**
   * App PlayCanvas và điều khiển camera của viewer khi sẵn sàng (null khi huỷ), để host gắn lớp
   * phủ cùng scene graph và cho camera bay tới vật.
   */
  onApp?: (app: ViewerAppLike | null, controls?: ViewerControls) => void;
  /** Hệ số nhân bước cuộn chuột (1 = mặc định của viewer). Đổi không tạo lại viewer. */
  wheelFactor?: number;
}

export interface ViewerAnnotation {
  position: [number, number, number];
  title: string;
  camera: DisplayCameraPose;
}

/** Điều khiển camera qua API công khai của supersplat-viewer (`selectAnnotation`). */
export interface ViewerControls {
  /** Bay tới annotation thứ `index`; false nếu viewer chưa nạp xong (API yêu cầu `state.loaded`). */
  select(index: number): boolean;
  /** Bật/tắt điều khiển camera của viewer (tắt trong lúc kéo gizmo để hai bên không tranh con trỏ). */
  setInputEnabled(enabled: boolean): void;
  /**
   * Chuyển chế độ camera. `walk` chỉ được khi viewer báo `walkAllowed` (có dữ liệu va chạm và scene
   * đủ lớn). Trả false khi viewer chưa nạp xong hoặc chế độ không dùng được.
   */
  setCameraMode(mode: Exclude<CameraMode, "anim">): boolean;
  /** Đưa cả scene vào khung hình (chuyển về xoay quanh tâm); false nếu viewer chưa nạp xong. */
  frameScene(): boolean;
  /** Về vị trí ban đầu của chế độ hiện tại; false nếu viewer chưa nạp xong. */
  resetCamera(): boolean;
}

export function PlayCanvasScene({
  contentUrl,
  renderer = "webgpu",
  contentFile,
  contentFilename,
  showControls = false,
  collisionUrl,
  mode,
  capability,
  onFailed,
  onRuntime,
  enableInspection = false,
  inspectionMaxPoints = 2,
  onInspectionReady,
  onInspectionState,
  sourceFrame = "colmap",
  initialCamera,
  annotations,
  onApp,
  wheelFactor = 1,
}: PlayCanvasSceneProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const wheel = useRef(wheelFactor);
  useEffect(() => {
    wheel.current = wheelFactor;
  }, [wheelFactor]);
  useEffect(() => {
    const host = container.current;
    if (!host) return;
    // Bắt ở pha capture trên host (trước canvas của viewer), thay bằng sự kiện đã nhân hệ số.
    // Sự kiện tự tạo có `isTrusted = false` nên đi thẳng tới viewer, không lặp vô hạn.
    const rescale = (event: WheelEvent) => {
      if (!event.isTrusted || wheel.current === 1 || !(event.target instanceof Element)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      event.target.dispatchEvent(new WheelEvent("wheel", scaledWheelInit(event, wheel.current)));
    };
    host.addEventListener("wheel", rescale, { capture: true, passive: false });
    return () => host.removeEventListener("wheel", rescale, { capture: true });
  }, []);
  const [runtime, setRuntime] = useState<PlayCanvasRuntime>(INITIAL_RUNTIME);

  /** Đẩy trạng thái lên host; giữ identity ổn định vì nằm trong deps của effect khác. */
  const publish = useCallback(
    (next: PlayCanvasRuntime) => {
      setRuntime(next);
      onRuntime?.(next);
    },
    [onRuntime],
  );

  useEffect(() => {
    if (capability !== "ready" || (!contentUrl && !contentFile) || mode !== "VISUAL" || !container.current) {
      return;
    }
    let disposed = false;
    let handle: ViewerHandleLike | null = null;
    let inspection: SplatInspection | null = null;
    const subscriptions: { off(): void }[] = [];
    const host = container.current;
    const objectUrl = contentFile ? URL.createObjectURL(contentFile) : null;
    const resolvedUrl = objectUrl ?? contentUrl!;

    let orient: (() => void) | null = null;

    void Promise.all([import("@playcanvas/supersplat-viewer/viewer"), import("@playcanvas/supersplat-viewer/settings")])
      .then(async ([module, settingsModule]) => {
        if (disposed) return;
        const settings = settingsModule.defaultSettings("environment");
        if (initialCamera) settings.cameras = [{ initial: initialCamera }];
        if (annotations?.length) {
          settings.annotations = annotations.map((item) => ({
            position: item.position,
            title: item.title,
            text: "",
            camera: { initial: item.camera },
          }));
        }
        const viewer = await module.createViewer({
          container: host,
          contentUrl: resolvedUrl,
          contentFilename: contentFile?.name ?? contentFilename ?? new URL(resolvedUrl, window.location.href).pathname.split("/").pop(),
          collisionUrl: collisionUrl ?? undefined,
          // `{}` làm viewer 1.35.2 crash ("reading 'color'") khi chạy browser thật
          // (2026-09-29); dùng default chính thức của thư viện, camera khung môi trường.
          settings,
          renderer,
          ui: showControls,
        });
        if (disposed) {
          viewer.destroy();
          return;
        }
        handle = viewer;
        // Upstream tạo entity `gsplat` khi asset nạp xong, với phép xoay COLMAP cố định. Đặt lại
        // phép xoay theo hệ nguồn ở frame đầu tiên có entity (trước khi render), rồi bỏ listener.
        const app = viewer.app as unknown as ViewerAppLike | undefined;
        if (app && sourceFrame !== "colmap") {
          const [ex, ey, ez] = DISPLAY_EULER[sourceFrame];
          orient = () => {
            const entity = app.root?.findByName("gsplat");
            if (!entity) return;
            entity.setLocalEulerAngles(ex, ey, ez);
            app.off("update", orient!);
            orient = null;
          };
          app.on("update", orient);
        }
        if (annotations?.length) viewer.state.showAnnotations = false;
        if (app) {
          onApp?.(app, {
            select: (index) => {
              if (disposed || !viewer.state.loaded) return false;
              viewer.selectAnnotation(index);
              return true;
            },
            setInputEnabled: (enabled) => {
              if (!disposed) viewer.state.inputEnabled = enabled;
            },
            setCameraMode: (next) => {
              if (disposed || !viewer.state.loaded) return false;
              if (next === "walk" && !viewer.state.walkAllowed) return false;
              viewer.state.cameraMode = next;
              return true;
            },
            frameScene: () => {
              if (disposed || !viewer.state.loaded) return false;
              viewer.frameScene();
              return true;
            },
            resetCamera: () => {
              if (disposed || !viewer.state.loaded) return false;
              viewer.resetCamera();
              return true;
            },
          });
        }
        let autoFramed = false;
        const tryAutoFrame = () => {
          if (!autoFramed && viewer.state.loaded && !initialCamera) {
            autoFramed = true;
            setTimeout(() => {
              if (!disposed && viewer.state.loaded) {
                viewer.frameScene();
              }
            }, 60);
          }
        };
        tryAutoFrame();

        // EventHandler của PlayCanvas bắn `<key>:changed`; `on` trả EventHandle
        // để huỷ. Không tự poll `state` vì đó là nguồn thật của thư viện.
        for (const event of ["progress:changed", "loaded:changed", "hasCollision:changed", "walkAllowed:changed", "cameraMode:changed"]) {
          subscriptions.push(viewer.events.on(event, () => {
            if (!disposed) {
              if (event === "loaded:changed") tryAutoFrame();
              publish(readRuntime(viewer));
            }
          }));
        }
        if (viewer.app?.assets) {
          subscriptions.push(viewer.app.assets.on("error", () => { if (!disposed) onFailed(); }));
        }
        publish(readRuntime(viewer));
        if (enableInspection && onInspectionState) {
          try {
            const { SplatInspection } = await import("./splat-inspection");
            if (disposed) return;
            inspection = new SplatInspection(viewer, onInspectionState, inspectionMaxPoints);
            onInspectionReady?.(inspection);
          } catch (error: unknown) {
            if (!disposed) onInspectionState({ ...EMPTY_INSPECTION, error: "Không khởi tạo được công cụ inspection; viewer vẫn dùng được." });
            console.error("Inspection initialization failed", error);
          }
        }
      })
      .catch((error: unknown) => {
        if (!disposed) {
          onFailed();
          console.error("supersplat-viewer init failed", error);
        }
      });

    return () => {
      disposed = true;
      subscriptions.forEach((subscription) => subscription.off());
      if (orient && handle?.app) (handle.app as unknown as ViewerAppLike).off("update", orient);
      onApp?.(null);
      onInspectionReady?.(null);
      const activeHandle = handle;
      const release = () => {
        activeHandle?.destroy();
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      };
      // GPU readback phải kết thúc trước khi hủy device mà nó còn đang dùng.
      if (inspection) void inspection.destroy().then(release, (error: unknown) => {
        console.error("Inspection cleanup failed", error);
        release();
      });
      else release();
      handle = null;
    };
  }, [capability, collisionUrl, contentUrl, contentFile, contentFilename, showControls, mode, onFailed, publish,
    enableInspection, inspectionMaxPoints, onInspectionReady, onInspectionState, renderer, sourceFrame, initialCamera,
    annotations, onApp]);

  return (
    <div
      ref={container}
      data-testid="playcanvas-scene"
      data-mode={mode}
      data-capability={capability}
      data-loaded={runtime.loaded}
      data-progress={Math.round(runtime.progress)}
      data-renderer={runtime.graphicsBackend}
      className="h-full w-full"
      data-engine={capability === "ready" ? "playcanvas" : undefined}
    />
  );
}

/** Phần của `pc.AppBase` mà host dùng (tìm entity, sự kiện frame, gắn lớp phủ). */
export interface ViewerAppLike {
  readonly root: {
    findByName(name: string): { setLocalEulerAngles(x: number, y: number, z: number): void; enabled: boolean } | null;
  };
  on(event: "update", handler: () => void): unknown;
  off(event: "update", handler: () => void): unknown;
}

/** Chỉ những field host thật sự dùng, để không phụ thuộc shape đầy đủ của thư viện. */
interface ViewerHandleLike {
  readonly app?: { readonly graphicsDevice: { readonly deviceType: string } };
  readonly state: { loaded: boolean; progress: number; hasCollision: boolean; walkAllowed: boolean; cameraMode: CameraMode };
  readonly events: { on(key: string, handler: () => void): { off(): void } };
  frameScene(): void;
  resetCamera(): void;
  toggleWalk(): void;
  destroy(): void;
}

function readRuntime(viewer: ViewerHandleLike): PlayCanvasRuntime {
  return {
    loaded: viewer.state.loaded,
    progress: Number.isFinite(viewer.state.progress) ? Math.max(0, Math.min(100, viewer.state.progress)) : 0,
    hasCollision: viewer.state.hasCollision,
    walkAllowed: viewer.state.walkAllowed,
    cameraMode: viewer.state.cameraMode,
    graphicsBackend: viewer.app?.graphicsDevice.deviceType,
  };
}
