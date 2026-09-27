"use client";

/**
 * Visual 3DGS của viewer, render bằng `@playcanvas/supersplat-viewer`.
 *
 * Theo `INTEGRATION_PLAYBOOK:745`, mọi lớp phải ở chung một scene graph. Ở đây
 * `createViewer()` sở hữu `pc.AppBase` và ta lấy `viewer.app.root` để thêm lớp
 * kỹ thuật (mesh/collider) vào **cùng** app đó — không phải hai engine song song.
 *
 * Vì sao vẫn còn Three.js: máy hiện tại không có WebGPU, mà supersplat ưu tiên
 * WebGPU. `SceneCanvas` giữ làm fallback cho tới khi PlayCanvas được qualification
 * với real Brush `VisualArtifact`. Xem `PRODUCT-06.md` §13.1.
 *
 * Transform không lấy từ state của PlayCanvas mà từ `layers.ts`, để cả hai renderer
 * cùng đọc một nguồn canonical của SceneIR.
 */

import { useEffect, useRef } from "react";

import type { ViewMode } from "@/features/viewer/layers";

/** Runtime capability của browser, đo trước khi gọi createViewer để tránh throw. */
export type PlayCanvasCapability = "unknown" | "ready" | "unavailable" | "failed";

export interface PlayCanvasSceneProps {
  /** URL của SOG đã resolve qua artifact endpoint; null nghĩa là chưa có Visual. */
  contentUrl: string | null;
  mode: ViewMode;
  /** Đo một lần ở host, để degraded state của cả viewer chỉ có một nguồn sự thật. */
  capability: PlayCanvasCapability;
  onFailed: () => void;
}

/**
 * `webgl` yêu cầu cứng: WebGPU là tuỳ chọn. Upstream mặc định `webgpu` và tự
 * fallback, nhưng AGENTS.md khóa WebGL2 là P0 baseline nên phải yêu cầu tường minh
 * để không phụ thuộc hành vi fallback của thư viện.
 */
const RENDERER = "webgl";

export function detectPlayCanvasCapability(): PlayCanvasCapability {
  if (typeof document === "undefined") {
    return "unknown";
  }
  const canvas = document.createElement("canvas");
  return canvas.getContext("webgl2") || canvas.getContext("webgl") ? "ready" : "unavailable";
}

export function PlayCanvasScene({ contentUrl, mode, capability, onFailed }: PlayCanvasSceneProps) {
  const container = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (capability !== "ready" || !contentUrl || mode !== "VISUAL" || !container.current) {
      return;
    }
    let disposed = false;
    let handle: { destroy(): void } | null = null;

    void import("@playcanvas/supersplat-viewer/viewer")
      .then(async (module) => {
        const viewer = await module.createViewer({
          container: container.current as HTMLElement,
          contentUrl,
          // Bắt buộc theo `CreateViewerOptions`. `{}` đi qua `migrateV1` nên viewer tự
          // điền default. Chưa verify bằng browser thật — xem `PRODUCT-06.md` §13.1.
          settings: {},
          renderer: RENDERER,
          ui: false,
        });
        if (disposed) {
          viewer.destroy();
          return;
        }
        handle = viewer;
        viewer.frameScene();
      })
      .catch(() => {
        if (!disposed) {
          onFailed();
        }
      });

    return () => {
      disposed = true;
      // Không destroy thì engine giữ GPU resource sau khi rời trang.
      handle?.destroy();
      handle = null;
    };
  }, [capability, contentUrl, mode, onFailed]);

  return (
    <div
      ref={container}
      data-testid="playcanvas-scene"
      data-mode={mode}
      data-capability={capability}
      className="h-full w-full"
      data-engine={capability === "ready" ? "playcanvas" : undefined}
    />
  );
}
