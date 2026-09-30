"use client";

import { Box, Check, Info, Loader2, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Badge, Button } from "@/components/studio/primitives";
import type { SaveState } from "@/features/studio/ObjectReviewView";
import type { StageState } from "@/features/studio/scene/state";
import { cn } from "@/lib/cn";

export function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors [&_svg]:size-3.5",
        active ? "border-ember bg-ember-soft text-ember-strong" : "border-line text-ink-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

/** Revision SceneIR + trạng thái lưu (Q5): không có nút "Lưu nháp", mỗi thao tác tự lưu. */
export function SaveStatus({ state }: { state: SaveState }) {
  if (state.status === "saving") {
    return (
      <Badge tone="neutral">
        <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />
        {state.revision} · Đang lưu…
      </Badge>
    );
  }
  if (state.status === "error") {
    return (
      <span className="flex items-center gap-1.5" role="alert">
        <Badge tone="rust" title={state.message}>
          <TriangleAlert aria-hidden />
          {state.revision} · Lưu lỗi
        </Badge>
        <Button size="sm" variant="ghost" onClick={state.retry}>
          Thử lại
        </Button>
      </span>
    );
  }
  return (
    <Badge tone="neutral" title="Mỗi thao tác trên vật thể được lưu thành một revision mới">
      <Check aria-hidden />
      {state.revision} · đã lưu
    </Badge>
  );
}

export function MetricBadge({ state }: { state: "waiting" | "confirmed" | "none" }) {
  return state === "confirmed" ? (
    <Badge tone="sage">
      <Check aria-hidden />
      Đã xác nhận tỉ lệ mét
    </Badge>
  ) : (
    <Badge tone="ochre" title="Preview dựng từ ảnh có đơn vị tuỳ ý; cần xác nhận tỉ lệ mét trước khi dựng hình học">
      <Info aria-hidden />
      Chưa quy đổi mét
    </Badge>
  );
}

export function GeometryBadge({ state }: { state: StageState }) {
  if (state === "running") {
    return (
      <Badge tone="ember">
        <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />
        Đang dựng collision
      </Badge>
    );
  }
  if (state === "succeeded") {
    return (
      <Badge tone="sage">
        <Box aria-hidden />
        Đã có collision mesh
      </Badge>
    );
  }
  if (state === "failed") {
    return (
      <Badge tone="rust">
        <TriangleAlert aria-hidden />
        Dựng collision lỗi
      </Badge>
    );
  }
  return null;
}
