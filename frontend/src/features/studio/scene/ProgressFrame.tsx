import type { ReactNode } from "react";

import { Card } from "@/components/studio/primitives";

/**
 * Khung chung của "Tiến trình xử lý": tiêu đề, một dòng mô tả và thẻ chứa dòng thời gian.
 *
 * Tab Tiến trình của scene thật và bản phát lại video mẫu đều dùng khung này để hai nơi trông như một, chỉ khác phần
 * dòng mô tả và những gì bỏ vào thẻ (hàng đợi, nút huỷ… ở scene thật; nút bỏ qua/mở scene ở bản phát lại).
 */
export function ProgressFrame({ hint, children }: { hint: ReactNode; children: ReactNode }) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold tracking-tight">Tiến trình xử lý</h2>
        <p className="mt-1 text-sm text-ink-muted">{hint}</p>
      </div>
      <Card className="p-5 sm:p-6">{children}</Card>
    </div>
  );
}
