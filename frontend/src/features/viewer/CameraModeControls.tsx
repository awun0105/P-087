"use client";

import { Footprints, Orbit, Plane } from "lucide-react";

import type { PlayCanvasRuntime, ViewerControls } from "@/features/viewer/PlayCanvasScene";
import { cn } from "@/lib/cn";

/**
 * Cụm nút chuyển chế độ camera (Xoay / Bay / Đi bộ) dùng chung cho các viewer 3DGS.
 * Tự động đọc trạng thái cameraMode và walkAllowed từ runtime PlayCanvas.
 */
export function CameraModeControls({
  runtime,
  controls,
  className,
}: {
  runtime: PlayCanvasRuntime;
  controls: ViewerControls | null;
  className?: string;
}) {
  const ready = runtime.loaded && controls !== null;
  const walkBlocked = !runtime.walkAllowed;

  return (
    <div className={cn("flex items-center gap-0.5 text-xs text-on-dark/80", className)}>
      <span className="text-[11px] text-on-dark/60 select-none mr-0.5">Chế độ:</span>
      <button
        type="button"
        disabled={!ready}
        aria-pressed={runtime.cameraMode === "orbit"}
        onClick={() => controls?.setCameraMode("orbit")}
        className={cn(
          "flex items-center gap-1 rounded px-1.5 py-0.5 text-xs transition-colors disabled:opacity-40",
          runtime.cameraMode === "orbit"
            ? "bg-ember-soft text-ember-strong font-medium"
            : "text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10",
        )}
        title="Xoay (Orbit): Kéo chuột trái để xoay, chuột phải để dời, cuộn để zoom; bấm đúp điểm để làm tâm xoay."
      >
        <Orbit className="size-3.5" aria-hidden />
        Xoay
      </button>
      <button
        type="button"
        disabled={!ready}
        aria-pressed={runtime.cameraMode === "fly"}
        onClick={() => controls?.setCameraMode("fly")}
        className={cn(
          "flex items-center gap-1 rounded px-1.5 py-0.5 text-xs transition-colors disabled:opacity-40",
          runtime.cameraMode === "fly"
            ? "bg-ember-soft text-ember-strong font-medium"
            : "text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10",
        )}
        title="Bay (Fly): W A S D để di chuyển, Q/E xuống/lên, giữ Shift để đi nhanh; kéo chuột nhìn quanh."
      >
        <Plane className="size-3.5" aria-hidden />
        Bay
      </button>
      <button
        type="button"
        disabled={!ready || walkBlocked}
        aria-pressed={runtime.cameraMode === "walk"}
        onClick={() => controls?.setCameraMode("walk")}
        className={cn(
          "flex items-center gap-1 rounded px-1.5 py-0.5 text-xs transition-colors disabled:opacity-40",
          runtime.cameraMode === "walk"
            ? "bg-ember-soft text-ember-strong font-medium"
            : "text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10",
          walkBlocked && "opacity-40 cursor-not-allowed",
        )}
        title={
          walkBlocked
            ? "Đi bộ cần lưới va chạm của scene (bước REC-05/06 trở đi) và scene đủ rộng."
            : "Đi bộ (Walk): W A S D để đi, Space để nhảy, giữ Shift để chạy; bị tường và sàn chặn lại."
        }
      >
        <Footprints className="size-3.5" aria-hidden />
        Đi bộ
      </button>
    </div>
  );
}
