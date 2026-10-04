"use client";

import type { ReactNode } from "react";

import { PreviewScene } from "@/features/studio/scene/PreviewScene";

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
}: {
  title: string;
  contentUrl: string;
  filename: string;
  badges?: ReactNode;
}) {
  return (
    <main className="relative flex h-[calc(100dvh-3rem)] flex-col">

      <div className="min-h-0 flex-1">
        <PreviewScene
          contentUrl={contentUrl}
          filename={filename}
          title={`Viewer 3DGS: ${title}`}
        />
      </div>
    </main>
  );
}
