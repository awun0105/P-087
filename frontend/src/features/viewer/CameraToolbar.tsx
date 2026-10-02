"use client";

import { Footprints, Maximize, Orbit, Plane, RotateCcw } from "lucide-react";
import type { ComponentType } from "react";

import type { CameraMode, PlayCanvasRuntime, ViewerControls } from "@/features/viewer/PlayCanvasScene";
import { cn } from "@/lib/cn";

type Mode = Exclude<CameraMode, "anim">;

const MODES: { mode: Mode; label: string; icon: ComponentType<{ className?: string }>; hint: string }[] = [
  { mode: "orbit", label: "Xoay", icon: Orbit, hint: "Kéo chuột trái để xoay, chuột phải để dời, cuộn để zoom; bấm đúp một điểm để lấy điểm đó làm tâm xoay." },
  { mode: "fly", label: "Bay", icon: Plane, hint: "W A S D để di chuyển, Q/E xuống/lên, giữ Shift để đi nhanh; kéo chuột để nhìn quanh." },
  { mode: "walk", label: "Đi bộ", icon: Footprints, hint: "W A S D để đi, Space để nhảy, giữ Shift để chạy; bị tường và vật thể chặn lại. Esc để nhả chuột." },
];

/** Các mức tốc độ zoom người dùng chọn được; 1 là mặc định của viewer. */
export const ZOOM_FACTORS = [1, 2, 4] as const;

/**
 * Thanh điều khiển camera của Studio trên viewer 3DGS: chuyển chế độ, về toàn cảnh, về vị trí
 * đầu, tốc độ zoom. Trạng thái (chế độ đang chạy, có đi bộ được không) đọc từ viewer, không tự giữ.
 */
export function CameraToolbar({
  runtime,
  controls,
  wheelFactor,
  onWheelFactor,
  className,
}: {
  runtime: PlayCanvasRuntime;
  controls: ViewerControls | null;
  wheelFactor: number;
  onWheelFactor: (factor: number) => void;
  className?: string;
}) {
  const ready = runtime.loaded && controls !== null;
  const active = MODES.find((item) => item.mode === runtime.cameraMode);
  const walkBlocked = !runtime.walkAllowed;
  const button = "flex items-center gap-1 rounded px-2 py-1 disabled:opacity-40";
  return (
    <div className={cn("rounded-md border border-line-dark bg-viewport-deep/85 px-2 py-1.5 text-xs text-on-dark/90", className)}>
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Điều khiển camera">
        {MODES.map(({ mode, label, icon: Icon }) => {
          const blocked = mode === "walk" && walkBlocked;
          return (
            <button
              key={mode}
              type="button"
              disabled={!ready || blocked}
              aria-pressed={runtime.cameraMode === mode}
              title={blocked ? "Đi bộ cần lưới va chạm của scene (có sau bước dựng hình học) và scene đủ rộng." : undefined}
              onClick={() => controls?.setCameraMode(mode)}
              className={cn(button, runtime.cameraMode === mode ? "bg-on-dark/20 font-medium" : "hover:bg-on-dark/10")}
            >
              <Icon className="size-3.5" aria-hidden />
              {label}
            </button>
          );
        })}
        <span className="mx-1 h-4 w-px bg-on-dark/20" aria-hidden />
        <button type="button" disabled={!ready} onClick={() => controls?.frameScene()} className={cn(button, "hover:bg-on-dark/10")}>
          <Maximize className="size-3.5" aria-hidden />
          Toàn cảnh
        </button>
        <button type="button" disabled={!ready} onClick={() => controls?.resetCamera()} className={cn(button, "hover:bg-on-dark/10")}>
          <RotateCcw className="size-3.5" aria-hidden />
          Về vị trí đầu
        </button>
        <label className="ml-1 flex items-center gap-1">
          Zoom
          <select
            value={wheelFactor}
            onChange={(event) => onWheelFactor(Number(event.target.value))}
            className="rounded bg-on-dark/10 px-1 py-0.5 text-on-dark"
            aria-label="Tốc độ zoom"
          >
            {ZOOM_FACTORS.map((factor) => (
              <option key={factor} value={factor} className="text-ink">
                {factor === 1 ? "chuẩn" : `nhanh ×${factor}`}
              </option>
            ))}
          </select>
        </label>
      </div>
      {active && <p className="mt-1 max-w-xl text-on-dark/70">{active.hint}</p>}
    </div>
  );
}
