"use client";

import { ArrowLeft, Check, Info, Ruler } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Badge, Button } from "@/components/studio/primitives";
import { EditorFrame } from "@/features/studio/EditorFrame";
import { MetricConfirmView } from "@/features/studio/MetricConfirmView";

/** Trạng thái tỉ lệ mét của scene người dùng (không có với scene mẫu). */
export interface SceneMetric {
  jobId: string;
  state: "waiting" | "confirmed" | "none";
  onConfirmed: () => void;
}

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
  metric,
}: {
  title: string;
  backHref: string;
  contentUrl: string;
  filename: string;
  badges?: ReactNode;
  metric?: SceneMetric;
}) {
  const [measuring, setMeasuring] = useState(false);
  const metricOpen = measuring && metric?.state === "waiting";
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
          {metric?.state === "waiting" && !metricOpen && (
            <Button size="sm" onClick={() => setMeasuring(true)}>
              <Ruler aria-hidden />
              Xác nhận tỉ lệ mét
            </Button>
          )}
        </div>
        <p className="ml-auto hidden text-xs text-ink-subtle lg:block">
          Chọn vùng để xóa/di chuyển · File › Export để tải PLY/SOG
        </p>
      </div>
      <div className="min-h-0 flex-1">
        {metricOpen && metric ? (
          <MetricConfirmView
            jobId={metric.jobId}
            contentUrl={contentUrl}
            filename={filename}
            onClose={() => setMeasuring(false)}
            onConfirmed={() => {
              setMeasuring(false);
              metric.onConfirmed();
            }}
          />
        ) : (
          <EditorFrame contentUrl={contentUrl} filename={filename} homeHref={backHref} title={`Editor 3D: ${title}`} />
        )}
      </div>
    </main>
  );
}
