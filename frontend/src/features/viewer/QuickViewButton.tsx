"use client";

import { Sparkles } from "lucide-react";

import type { QuickView } from "@/features/viewer/useQuickView";

/** Nút trên thanh công cụ viewer: đang xem bản nhanh thì cho tải bản đầy đủ (T-068). Không hiện khi đã ở bản đầy đủ. */
export function QuickViewButton({ view }: { view: QuickView }) {
  if (!view.quick) return null;
  return (
    <button
      type="button"
      className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors"
      onClick={view.showFull}
      title="Đang xem bản nhẹ (ít điểm, màu cơ bản). Bấm để tải chất lượng đầy đủ; góc nhìn trở về ban đầu."
      aria-label="Chất lượng đầy đủ"
    >
      <Sparkles className="size-4" aria-hidden />
    </button>
  );
}
