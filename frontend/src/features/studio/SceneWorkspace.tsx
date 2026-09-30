"use client";

import { ArrowLeft, Box, Boxes, Check, Columns3, Info, Layers, Loader2, Ruler, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Badge, Button } from "@/components/studio/primitives";
import { EditorFrame } from "@/features/studio/EditorFrame";
import { MetricConfirmView } from "@/features/studio/MetricConfirmView";
import { ModeComparisonView } from "@/features/studio/ModeComparisonView";
import { ObjectReviewView } from "@/features/studio/ObjectReviewView";
import { StageViewer } from "@/features/studio/StageViewer";

/** Trạng thái tỉ lệ mét của scene người dùng (không có với scene mẫu). */
export interface SceneMetric {
  jobId: string;
  state: "waiting" | "confirmed" | "none";
  onConfirmed: () => void;
}

/** Bước hình học/collision sau xác nhận tỉ lệ (REC-05/REC-10). */
export type GeometryState = "none" | "running" | "done" | "failed";

type Panel = "editor" | "metric" | "stages" | "compare" | "objects";

/**
 * Workspace toàn màn hình cho một scene 3DGS: thanh thông tin mảnh phía trên, phần
 * còn lại là editor, bước xác nhận tỉ lệ, hoặc kết quả từng bước của pipeline.
 */
export function SceneWorkspace({
  title,
  backHref,
  contentUrl,
  filename,
  badges,
  metric,
  geometry = "none",
  onRetryGeometry,
}: {
  title: string;
  backHref: string;
  contentUrl: string;
  filename: string;
  badges?: ReactNode;
  metric?: SceneMetric;
  geometry?: GeometryState;
  onRetryGeometry?: () => void;
}) {
  const [panel, setPanel] = useState<Panel>("editor");
  const shown: Panel = panel === "metric" && metric?.state !== "waiting" ? "editor" : panel;
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
          {metric?.state === "confirmed" ? (
            <Badge tone="sage">
              <Check aria-hidden />
              Đã xác nhận tỉ lệ mét
            </Badge>
          ) : (
            <Badge tone="ochre" title="Preview dựng từ ảnh có đơn vị tùy ý; cần xác nhận tỉ lệ mét trước khi dựng hình học">
              <Info aria-hidden />
              Tỉ lệ chưa quy đổi mét
            </Badge>
          )}
          <GeometryBadge state={geometry} />
          {geometry === "failed" && onRetryGeometry && (
            <Button size="sm" variant="secondary" onClick={onRetryGeometry} title="Chỉ chạy lại bước dựng collision, giữ preview và tỉ lệ đã xác nhận">
              Thử lại bước collision
            </Button>
          )}
          {metric?.state === "waiting" && shown !== "metric" && (
            <Button size="sm" onClick={() => setPanel("metric")}>
              <Ruler aria-hidden />
              Xác nhận tỉ lệ mét
            </Button>
          )}
          {metric && (
            <Button
              size="sm"
              variant={shown === "stages" ? "primary" : "secondary"}
              onClick={() => setPanel(shown === "stages" ? "editor" : "stages")}
            >
              <Layers aria-hidden />
              {shown === "stages" ? "Về editor" : "Kết quả từng bước"}
            </Button>
          )}
          {metric && geometry === "done" && (
            <Button
              size="sm"
              variant={shown === "objects" ? "primary" : "secondary"}
              onClick={() => setPanel(shown === "objects" ? "editor" : "objects")}
            >
              <Boxes aria-hidden />
              {shown === "objects" ? "Về editor" : "Vật thể"}
            </Button>
          )}
          {metric && (
            <Button
              size="sm"
              variant={shown === "compare" ? "primary" : "secondary"}
              onClick={() => setPanel(shown === "compare" ? "editor" : "compare")}
            >
              <Columns3 aria-hidden />
              {shown === "compare" ? "Về editor" : "So sánh 3 hướng"}
            </Button>
          )}
        </div>
        <p className="ml-auto hidden text-xs text-ink-subtle lg:block">
          Chọn vùng để xóa/di chuyển · File › Export để tải PLY/SOG
        </p>
      </div>
      <div className="min-h-0 flex-1">
        {shown === "metric" && metric ? (
          <MetricConfirmView
            jobId={metric.jobId}
            contentUrl={contentUrl}
            filename={filename}
            onClose={() => setPanel("editor")}
            onConfirmed={() => {
              setPanel("editor");
              metric.onConfirmed();
            }}
          />
        ) : shown === "stages" && metric ? (
          <StageViewer jobId={metric.jobId} />
        ) : shown === "objects" && metric ? (
          <ObjectReviewView jobId={metric.jobId} />
        ) : shown === "compare" && metric ? (
          <ModeComparisonView jobId={metric.jobId} />
        ) : (
          <EditorFrame contentUrl={contentUrl} filename={filename} homeHref={backHref} title={`Editor 3D: ${title}`} />
        )}
      </div>
    </main>
  );
}

function GeometryBadge({ state }: { state: GeometryState }) {
  if (state === "running") {
    return (
      <Badge tone="ember">
        <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />
        Đang dựng collision
      </Badge>
    );
  }
  if (state === "done") {
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
