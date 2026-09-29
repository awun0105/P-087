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
  graphicsBackend?: string;
}

export const INITIAL_RUNTIME: PlayCanvasRuntime = { loaded: false, progress: 0, hasCollision: false, walkAllowed: false };

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
  onInspectionReady?: (controller: SplatInspection | null) => void;
  onInspectionState?: (state: InspectionState) => void;
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
  onInspectionReady,
  onInspectionState,
}: PlayCanvasSceneProps) {
  const container = useRef<HTMLDivElement | null>(null);
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

    void Promise.all([import("@playcanvas/supersplat-viewer/viewer"), import("@playcanvas/supersplat-viewer/settings")])
      .then(async ([module, settingsModule]) => {
        if (disposed) return;
        const viewer = await module.createViewer({
          container: host,
          contentUrl: resolvedUrl,
          contentFilename: contentFile?.name ?? contentFilename ?? new URL(resolvedUrl, window.location.href).pathname.split("/").pop(),
          collisionUrl: collisionUrl ?? undefined,
          // `{}` làm viewer 1.35.2 crash ("reading 'color'") khi chạy browser thật
          // (2026-09-29); dùng default chính thức của thư viện, camera khung môi trường.
          settings: settingsModule.defaultSettings("environment"),
          renderer,
          ui: showControls,
        });
        if (disposed) {
          viewer.destroy();
          return;
        }
        handle = viewer;
        // EventHandler của PlayCanvas bắn `<key>:changed`; `on` trả EventHandle
        // để huỷ. Không tự poll `state` vì đó là nguồn thật của thư viện.
        for (const event of ["progress:changed", "loaded:changed", "hasCollision:changed", "walkAllowed:changed"]) {
          subscriptions.push(viewer.events.on(event, () => { if (!disposed) publish(readRuntime(viewer)); }));
        }
        if (viewer.app?.assets) {
          subscriptions.push(viewer.app.assets.on("error", () => { if (!disposed) onFailed(); }));
        }
        publish(readRuntime(viewer));
        if (enableInspection && onInspectionState) {
          try {
            const { SplatInspection } = await import("./splat-inspection");
            if (disposed) return;
            inspection = new SplatInspection(viewer, onInspectionState);
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
    enableInspection, onInspectionReady, onInspectionState, renderer]);

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

/** Chỉ những field host thật sự dùng, để không phụ thuộc shape đầy đủ của thư viện. */
interface ViewerHandleLike {
  readonly app?: { readonly graphicsDevice: { readonly deviceType: string } };
  readonly state: { loaded: boolean; progress: number; hasCollision: boolean; walkAllowed: boolean };
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
    graphicsBackend: viewer.app?.graphicsDevice.deviceType,
  };
}
