"use client";

import { Bookmark, Maximize, RotateCcw, PersonStanding } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  PlayCanvasScene,
  playCanvasErrorMessage,
  usePlayCanvasCapability,
  INITIAL_RUNTIME,
  type CameraMode,
  type ViewerControls,
} from "@/features/viewer/PlayCanvasScene";
import {
  recordingCameraPose,
  type CameraMarkerLike,
  type DisplayCameraPose,
  type SourceFrame,
} from "@/features/viewer/source-frame";
import { useJobCameras } from "@/features/studio/scene/useJobCameras";
import { cn } from "@/lib/cn";

/** Bản xem SfM trung tính; hỗ trợ góc nhìn camera ban đầu và điều hướng Fly/Walk/Orbit. */
export function PreviewScene({
  contentUrl,
  filename,
  title,
  jobId,
  initialCamera,
  initialCameraMode,
  cameras,
  sourceFrame = "colmap",
  onControlsReady,
  onSaveDefaultCamera,
  saveDefaultCameraStatus = "idle",
  currentBookmark,
  fallbackInitialCamera,
  onToggleBookmark,
  bookmarkStatus,
}: {
  contentUrl: string;
  filename: string;
  title?: string;
  /** Có `jobId` mà không có `cameras`/`initialCamera` thì tự lấy quỹ đạo camera của job để mở đầu bên trong scene. */
  jobId?: string;
  initialCamera?: DisplayCameraPose;
  initialCameraMode?: Exclude<CameraMode, "anim">;
  cameras?: readonly CameraMarkerLike[];
  sourceFrame?: SourceFrame;
  onControlsReady?: (controls: ViewerControls | null) => void;
  onSaveDefaultCamera?: (controls?: ViewerControls | null) => Promise<void> | void;
  saveDefaultCameraStatus?: "idle" | "saving" | "saved" | "error";
  currentBookmark?: DisplayCameraPose | null;
  fallbackInitialCamera?: DisplayCameraPose;
  onToggleBookmark?: (active: boolean, controls?: ViewerControls | null) => Promise<void> | void;
  bookmarkStatus?: "idle" | "saving" | "saved" | "error";
}) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const [viewerControls, setViewerControls] = useState<ViewerControls | null>(null);
  const [wheelFactor, setWheelFactor] = useState(2);
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const handleApp = useCallback((_app: unknown, controls?: ViewerControls) => {
    const ctrl = controls ?? null;
    setViewerControls(ctrl);
    onControlsReady?.(ctrl);
  }, [onControlsReady]);

  const handleResetCamera = useCallback(() => {
    if (!viewerControls) return;
    const targetPose = currentBookmark ?? fallbackInitialCamera;
    if (targetPose) {
      viewerControls.gotoPose(targetPose);
    } else {
      viewerControls.resetCamera();
    }
  }, [viewerControls, currentBookmark, fallbackInitialCamera]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "r" || e.key === "R") {
        const target = e.target as HTMLElement | null;
        if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
          return;
        }
        handleResetCamera();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleResetCamera]);

  const supplied = initialCamera !== undefined || (cameras?.length ?? 0) > 0;
  const fetched = useJobCameras(supplied ? undefined : jobId);
  const effectiveCameras = cameras ?? fetched.cameras;
  const resolvedCamera = useMemo(() => {
    if (initialCamera) return initialCamera;
    if (effectiveCameras && effectiveCameras.length > 0) return recordingCameraPose(sourceFrame, effectiveCameras);
    return undefined;
  }, [initialCamera, effectiveCameras, sourceFrame]);

  return (
    <div className="relative size-full bg-viewport" aria-label={title}>
      {capability === "failed" || capability === "unavailable" ? (
        <p role="alert" className="grid size-full place-items-center p-6 text-sm text-on-dark">
          {playCanvasErrorMessage(capability)}
        </p>
      ) : (
        <>
          {(!runtime.loaded || !fetched.settled) && (
            <p
              role="status"
              className="absolute top-3 left-3 z-10 rounded border border-line-dark bg-viewport-deep/85 p-2 text-sm text-on-dark"
            >
              Đang tải bản xem 3DGS…
            </p>
          )}
          {fetched.settled && (
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
              cameras={effectiveCameras}
              wheelFactor={wheelFactor}
              initialCamera={resolvedCamera}
              initialCameraMode={initialCameraMode ?? (jobId ? "fly" : "orbit")}
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
                    onClick={handleResetCamera}
                    disabled={!runtime.loaded}
                    title={currentBookmark ? "Về góc nhìn đã lưu (R)" : "Về vị trí ban đầu (R)"}
                    aria-label={currentBookmark ? "Về góc nhìn đã lưu" : "Về vị trí ban đầu"}
                  >
                    <RotateCcw className="size-4" aria-hidden />
                  </button>
                  {(onToggleBookmark || onSaveDefaultCamera) && (
                    <button
                      type="button"
                      className={cn(
                        "sse-controlButton flex items-center justify-center transition-colors disabled:opacity-40",
                        (bookmarkStatus === "saving" || saveDefaultCameraStatus === "saving")
                          ? "text-amber-400 animate-pulse"
                          : (bookmarkStatus === "error" || saveDefaultCameraStatus === "error")
                            ? "text-rose-400 bg-rose-500/10"
                            : currentBookmark
                              ? "text-amber-400 bg-amber-400/20 hover:bg-amber-400/30"
                              : "text-on-dark/80 hover:text-on-dark",
                      )}
                      onClick={() => {
                        if (onToggleBookmark) {
                          void onToggleBookmark(!currentBookmark, viewerControls);
                        } else if (onSaveDefaultCamera) {
                          void onSaveDefaultCamera(viewerControls);
                        }
                      }}
                      disabled={!runtime.loaded || bookmarkStatus === "saving" || saveDefaultCameraStatus === "saving"}
                      title={
                        (bookmarkStatus === "saving" || saveDefaultCameraStatus === "saving")
                          ? "Đang lưu góc nhìn…"
                          : (bookmarkStatus === "error" || saveDefaultCameraStatus === "error")
                            ? "Lỗi lưu góc nhìn (bấm để thử lại)"
                            : currentBookmark
                              ? "Gỡ góc nhìn mặc định (quay lại góc nhìn mặc định ban đầu)"
                              : "Đặt làm góc nhìn mặc định"
                      }
                      aria-label={currentBookmark ? "Gỡ góc nhìn mặc định" : "Đặt làm góc nhìn mặc định"}
                    >
                      <Bookmark
                        className={cn("size-4", currentBookmark && "fill-current")}
                        aria-hidden
                      />
                    </button>
                  )}
                  <button
                    type="button"
                    className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors opacity-40 cursor-not-allowed"
                    disabled
                    title="Góc nhìn thứ ba (Cần hoàn tất dựng hình học để bật)"
                    aria-label="Góc nhìn thứ ba"
                  >
                    <PersonStanding className="size-4" aria-hidden />
                  </button>
                  <div className="flex items-center gap-0.5 border-l border-line-dark px-1.5 text-xs text-on-dark/80">
                    <span className="text-[11px] text-on-dark/60 select-none mr-0.5">Zoom:</span>
                    {[1, 2, 4].map((factor) => (
                      <button
                        key={factor}
                        type="button"
                        onClick={() => setWheelFactor(factor)}
                        className={cn(
                          "rounded px-1.5 py-0.5 text-xs transition-colors",
                          wheelFactor === factor
                            ? "bg-ember-soft text-ember-strong font-medium"
                            : "text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10",
                        )}
                        title={`Tốc độ zoom ${factor === 1 ? "chuẩn (×1)" : `nhanh (×${factor})`}`}
                      >
                        {factor}×
                      </button>
                    ))}
                  </div>
                </div>
              }
            />
          )}
        </>
      )}
    </div>
  );
}
