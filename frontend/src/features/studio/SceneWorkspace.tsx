"use client";

import type { ReactNode } from "react";

import { EditorFrame } from "@/features/studio/EditorFrame";

/**
 * Workspace chỉ xem/chỉnh 3DGS cho scene không có pipeline hệ mét (video mẫu, file import):
 * thanh thông tin mảnh + editor SuperSplat. Scene dựng từ video dùng `ScenePage` (4 tab D-07).
 * Quay lại danh sách đi qua breadcrumb của AppShell nên không lặp nút "Quay lại" ở đây.
 */
export function SceneWorkspace({
  title,
  backHref,
  contentUrl,
  filename,
  badges,
}: {
  title: string;
  backHref: string;
  contentUrl: string;
  filename: string;
  badges?: ReactNode;
}) {
  return (
    <main className="flex h-[calc(100dvh-3rem)] flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-paper-raised px-4 py-2.5 sm:px-6">
        <h1 className="truncate text-base font-semibold text-ink">{title}</h1>
        <div className="flex flex-wrap items-center gap-2">{badges}</div>
      </div>
      <p className="border-b border-line bg-paper px-4 py-2 text-xs text-ink-muted sm:px-6">
        Chỉnh Gaussian trong phiên editor · File › Export để tải PLY/SOG · thay đổi không lưu thành SceneIR revision.
      </p>
      <div className="min-h-0 flex-1">
        <EditorFrame contentUrl={contentUrl} filename={filename} homeHref={backHref} title={`Editor 3D: ${title}`} />
      </div>
    </main>
  );
}
