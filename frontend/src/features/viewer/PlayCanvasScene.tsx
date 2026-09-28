"use client";

/**
 * Visual 3DGS của viewer, render bằng `@playcanvas/supersplat-viewer`.
 *
 * Căn cứ: `INTEGRATION_PLAYBOOK:745` và `PRODUCT-06.md` §13.1. Ba điều phải nói
 * rõ vì chúng quyết định hành vi thật:
 *
 * 1. **Renderer là `webgl` tường minh.** Upstream mặc định `webgpu` và tự fallback,
 *    còn `AGENTS.md:240` khóa WebGL2 là P0 baseline nên không được phụ thuộc hành đó.
 * 2. **Collider đi qua `collisionUrl` của chính viewer**, nên collider GLB nằm trong
 *    cùng `pc.AppBase` với SOG — đây là phần Single Scene Graph mà
 *    `TRACK.md:39` yêu cầu, và là lý do không tự dựng mesh trong engine thứ hai.
 *    Lớp kỹ thuật còn lại vẫn do `SceneCanvas` lo; xem `PRODUCT-06.md` §13.1.
 * 3. **Trạng thái load/camera đọc từ `viewer.state`**, không tự bịa thanh tiến trình:
 *    `state.progress` là 0..100 và `state.loaded` chỉ true sau frame đầu.
 *
 * Transform không lấy từ state của PlayCanvas mà từ `layers.ts`, để renderer nào
 * cũng đọc cùng một nguồn canonical của SceneIR.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { ViewMode } from "@/features/viewer/layers";

import "@playcanvas/supersplat-viewer/viewer.css";

/** Runtime capability của browser, đo trước khi gọi createViewer để tránh throw. */
export type PlayCanvasCapability = "unknown" | "ready" | "unavailable" | "failed";

/** Trạng thái runtime lấy từ `ViewerHandle.state` của thư viện, không phải tự đếm. */
export interface PlayCanvasRuntime {
  loaded: boolean;
  progress: number;
  hasCollision: boolean;
  walkAllowed: boolean;
}

const RENDERER = "webgl";
export const INITIAL_RUNTIME: PlayCanvasRuntime = { loaded: false, progress: 0, hasCollision: false, walkAllowed: false };

export function detectPlayCanvasCapability(): PlayCanvasCapability {
  if (typeof document === "undefined") {
    return "unknown";
  }
  const canvas = document.createElement("canvas");
  try {
    const gl = canvas.getContext("webgl2");
    gl?.getExtension?.("WEBGL_lose_context")?.loseContext();
    return gl ? "ready" : "unavailable";
  } catch {
    return "unavailable";
  }
}

export interface PlayCanvasSceneProps {
  /** URL của SOG đã resolve qua artifact endpoint; null nghĩa là chưa có Visual. */
  contentUrl: string | null;
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
}

export function PlayCanvasScene({
  contentUrl,
  contentFile,
  contentFilename,
  showControls = false,
  collisionUrl,
  mode,
  capability,
  onFailed,
  onRuntime,
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
    const subscriptions: { off(): void }[] = [];
    const host = container.current;
    const objectUrl = contentFile ? URL.createObjectURL(contentFile) : null;
    const resolvedUrl = objectUrl ?? contentUrl!;

    void import("@playcanvas/supersplat-viewer/viewer")
      .then(async (module) => {
        if (disposed) return;
        const viewer = await module.createViewer({
          container: host,
          contentUrl: resolvedUrl,
          contentFilename: contentFile?.name ?? contentFilename ?? new URL(resolvedUrl, window.location.href).pathname.split("/").pop(),
          collisionUrl: collisionUrl ?? undefined,
          // Bắt buộc theo `CreateViewerOptions`. `{}` đi qua `migrateV1` nên viewer tự
          // điền default. Chưa verify bằng browser thật — xem `PRODUCT-06.md` §13.1.
          settings: {},
          renderer: RENDERER,
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
      // Không destroy thì engine giữ GPU resource sau khi rời trang.
      handle?.destroy();
      handle = null;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [capability, collisionUrl, contentUrl, contentFile, contentFilename, showControls, mode, onFailed, publish]);

  return (
    <div
      ref={container}
      data-testid="playcanvas-scene"
      data-mode={mode}
      data-capability={capability}
      data-loaded={runtime.loaded}
      data-progress={Math.round(runtime.progress)}
      className="h-full w-full"
      data-engine={capability === "ready" ? "playcanvas" : undefined}
    />
  );
}

/** Chỉ những field host thật sự dùng, để không phụ thuộc shape đầy đủ của thư viện. */
interface ViewerHandleLike {
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
  };
}
