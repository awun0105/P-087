"use client";

import type { ReactNode } from "react";

import { PreviewScene } from "@/features/studio/scene/PreviewScene";
import type { CameraMode, ViewerControls } from "@/features/viewer/PlayCanvasScene";
import type { CameraMarkerLike, DisplayCameraPose } from "@/features/viewer/source-frame";

/**
 * Workspace chỉ xem 3DGS cho scene không có pipeline hệ mét (video mẫu, file import):
 * thanh thông tin mảnh + PreviewScene. Scene dựng từ video dùng `ScenePage` (4 tab D-07).
 * Quay lại danh sách đi qua breadcrumb của AppShell nên không lặp nút "Quay lại" ở đây.
 */
export function SceneWorkspace({
  title,
  contentUrl,
  filename,
  badges,
  cameras,
  initialCamera,
  initialCameraMode,
  onControlsReady,
  onSaveDefaultCamera,
  saveDefaultCameraStatus,
  currentBookmark,
  fallbackInitialCamera,
  onToggleBookmark,
  bookmarkStatus,
}: {
  title: string;
  contentUrl: string;
  filename: string;
  badges?: ReactNode;
  cameras?: readonly CameraMarkerLike[];
  initialCamera?: DisplayCameraPose;
  initialCameraMode?: Exclude<CameraMode, "anim">;
  onControlsReady?: (controls: ViewerControls | null) => void;
  onSaveDefaultCamera?: (controls?: ViewerControls | null) => Promise<void> | void;
  saveDefaultCameraStatus?: "idle" | "saving" | "saved" | "error";
  currentBookmark?: DisplayCameraPose | null;
  fallbackInitialCamera?: DisplayCameraPose;
  onToggleBookmark?: (active: boolean, controls?: ViewerControls | null) => Promise<void> | void;
  bookmarkStatus?: "idle" | "saving" | "saved" | "error";
}) {
  return (
    <main className="relative flex h-[calc(100dvh-3rem)] flex-col">
      {badges ? <div className="absolute top-2 right-2 z-10 flex items-center gap-1.5">{badges}</div> : null}
      <div className="min-h-0 flex-1">
        <PreviewScene
          contentUrl={contentUrl}
          filename={filename}
          title={`Viewer 3DGS: ${title}`}
          cameras={cameras}
          initialCamera={initialCamera}
          initialCameraMode={initialCameraMode}
          onControlsReady={onControlsReady}
          onSaveDefaultCamera={onSaveDefaultCamera}
          saveDefaultCameraStatus={saveDefaultCameraStatus}
          currentBookmark={currentBookmark}
          fallbackInitialCamera={fallbackInitialCamera}
          onToggleBookmark={onToggleBookmark}
          bookmarkStatus={bookmarkStatus}
        />
      </div>
    </main>
  );
}
