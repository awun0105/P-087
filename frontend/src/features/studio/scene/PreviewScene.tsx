"use client";
import { Maximize, RotateCcw, PersonStanding } from "lucide-react";
import { useCallback, useState } from "react";
import {
  PlayCanvasScene,
  usePlayCanvasCapability,
  INITIAL_RUNTIME,
  type ViewerControls,
} from "@/features/viewer/PlayCanvasScene";
import type { SourceFrame } from "@/features/viewer/source-frame";
import { cn } from "@/lib/cn";
import type { Preview } from "@/features/studio/scene/state";

/** Bản xem SfM trung tính; chỉnh Gaussian chỉ mở khi người dùng chọn chế độ đó. */
export function PreviewScene({ contentUrl, filename, title }: { contentUrl: string; filename: string; title?: string }) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const [viewerControls, setViewerControls] = useState<ViewerControls | null>(null);
  const [sourceFrame, setSourceFrame] = useState<SourceFrame>("colmap");
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const handleApp = useCallback((_app: unknown, controls?: ViewerControls) => {
    setViewerControls(controls ?? null);
  }, []);

  return (
    <div className="relative size-full bg-viewport">
      {capability === "failed" || capability === "unavailable" ? (
        <p role="alert" className="grid size-full place-items-center p-6 text-sm text-on-dark">
          Không mở được 3DGS. Trình duyệt cần WebGL2/WebGPU và đủ bộ nhớ GPU.
        </p>
      ) : (
        <>
          {!runtime.loaded && (
            <p
              role="status"
              className="absolute top-3 left-3 z-10 rounded border border-line-dark bg-viewport-deep/85 p-2 text-sm text-on-dark"
            >
              Đang tải bản xem 3DGS…
            </p>
          )}
          <PlayCanvasScene
            contentUrl={contentUrl}
            contentFilename={filename}
            renderer="webgl"
            mode="VISUAL"
            showControls
            capability={capability}
            onFailed={fail}
            onRuntime={setRuntime}
            sourceFrame={sourceFrame}
            onApp={handleApp}
            extraControls={
              <div
                className="sse-buttonGroup flex items-center shrink-0 border border-line-dark"
                onPointerDown={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors disabled:opacity-40"
                  onClick={() => viewerControls?.frameScene()}
                  disabled={!runtime.loaded}
                  title="Toàn cảnh (F)"
                  aria-label="Toàn cảnh"
                >
                  <Maximize className="size-4" aria-hidden />
                </button>
                <button
                  type="button"
                  className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors disabled:opacity-40"
                  onClick={() => viewerControls?.resetCamera()}
                  disabled={!runtime.loaded}
                  title="Về vị trí ban đầu (R)"
                  aria-label="Về vị trí ban đầu"
                >
                  <RotateCcw className="size-4" aria-hidden />
                </button>
                <button
                  type="button"
                  className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors opacity-40 cursor-not-allowed"
                  disabled
                  title="Góc nhìn thứ ba (Cần hoàn tất dựng hình học để bật)"
                  aria-label="Góc nhìn thứ ba"
                >
                  <PersonStanding className="size-4" aria-hidden />
                </button>
                <div className="flex items-center gap-1 border-l border-line-dark px-2 text-xs text-on-dark/80">
                  <span className="text-[11px] text-on-dark/60 select-none">Trục:</span>
                  <button
                    type="button"
                    className={cn(
                      "rounded px-1.5 py-0.5 text-xs transition-colors",
                      sourceFrame === "colmap"
                        ? "bg-ember-soft text-ember-strong font-medium"
                        : "text-on-dark/70 hover:text-on-dark",
                    )}
                    onClick={() => setSourceFrame("colmap")}
                    title="COLMAP / Brush (Y hướng xuống, xoay 180° quanh Z)"
                  >
                    COLMAP
                  </button>
                  <button
                    type="button"
                    className={cn(
                      "rounded px-1.5 py-0.5 text-xs transition-colors",
                      sourceFrame === "z_up"
                        ? "bg-ember-soft text-ember-strong font-medium"
                        : "text-on-dark/70 hover:text-on-dark",
                    )}
                    onClick={() => setSourceFrame("z_up")}
                    title="Chuẩn Z-up (Quay trục Z lên trên, sàn z=0)"
                  >
                    Z-up
                  </button>
                  <button
                    type="button"
                    className={cn(
                      "rounded px-1.5 py-0.5 text-xs transition-colors",
                      sourceFrame === "identity"
                        ? "bg-ember-soft text-ember-strong font-medium"
                        : "text-on-dark/70 hover:text-on-dark",
                    )}
                    onClick={() => setSourceFrame("identity")}
                    title="Gốc (Không xoay trục)"
                  >
                    Gốc
                  </button>
                </div>
              </div>
            }
          />
        </>
      )}
    </div>
  );
}
