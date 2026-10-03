"use client";

import { RotateCcw } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/studio/primitives";
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
  resettable = false,
}: {
  title: string;
  backHref: string;
  contentUrl: string;
  filename: string;
  badges?: ReactNode;
  /** Có nút "Khôi phục bản gốc": nạp lại file gốc vào editor, bỏ mọi chỉnh sửa trong phiên (vd scene mẫu). */
  resettable?: boolean;
}) {
  // Đổi `key` buộc editor nhúng tạo lại từ file gốc; file gốc không bao giờ bị ghi đè nên không cần gọi máy chủ.
  const [session, setSession] = useState(0);
  function reset() {
    if (window.confirm("Khôi phục bản gốc? Mọi chỉnh sửa trong phiên editor này sẽ mất (file đã Export không bị ảnh hưởng).")) {
      setSession((value) => value + 1);
    }
  }
  return (
    <main className="flex h-[calc(100dvh-3rem)] flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-paper-raised px-4 py-2.5 sm:px-6">
        <h1 className="truncate text-base font-bold text-ink">{title}</h1>
        <div className="flex flex-wrap items-center gap-2">{badges}</div>
        {resettable && (
          <Button size="sm" variant="secondary" className="ml-auto" onClick={reset}>
            <RotateCcw aria-hidden />
            Khôi phục bản gốc
          </Button>
        )}
      </div>
      <p className="border-b border-line bg-paper px-4 py-2 text-xs text-ink-muted sm:px-6">
        Chỉnh Gaussian trong phiên editor · File › Export để tải PLY/SOG · thay đổi không lưu thành SceneIR revision.
      </p>
      <div className="min-h-0 flex-1">
        <EditorFrame key={session} contentUrl={contentUrl} filename={filename} homeHref={backHref} title={`Editor 3D: ${title}`} />
      </div>
    </main>
  );
}
