"use client";

import { ArrowLeft, Info } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/studio/primitives";
import { EditorFrame } from "@/features/studio/EditorFrame";

/**
 * Workspace toàn màn hình cho một scene 3DGS: thanh thông tin mảnh phía trên,
 * editor nhúng chiếm phần còn lại. Nhãn tỉ lệ nói rõ preview chưa quy đổi mét.
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
    <main className="flex h-[calc(100dvh-4rem)] flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-paper-raised px-4 py-2.5 sm:px-6">
        <Link
          href={backHref}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm text-ink-muted transition-colors hover:bg-paper-sunken hover:text-ink"
        >
          <ArrowLeft className="size-4" aria-hidden />
          Quay lại
        </Link>
        <h1 className="truncate text-sm font-semibold text-ink">{title}</h1>
        <div className="flex flex-wrap items-center gap-2">
          {badges}
          <Badge tone="ochre" title="Preview dựng từ ảnh có đơn vị tùy ý; xác nhận tỉ lệ mét là bước sau MVP">
            <Info aria-hidden />
            Tỉ lệ chưa quy đổi mét
          </Badge>
        </div>
        <p className="ml-auto hidden text-xs text-ink-subtle lg:block">
          Chọn vùng để xóa/di chuyển · File › Export để tải PLY/SOG
        </p>
      </div>
      <div className="min-h-0 flex-1">
        <EditorFrame contentUrl={contentUrl} filename={filename} homeHref={backHref} title={`Editor 3D: ${title}`} />
      </div>
    </main>
  );
}
