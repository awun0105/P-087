"use client";

import { errorMessage } from "@/lib/ui-error";

import { BadgeCheck, Loader2, Radar, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Badge, Card, Notice } from "@/components/studio/primitives";
import { getModeComparison } from "@/lib/api/studio";
import type { ModeComparison, ModeResult } from "@/lib/contracts/studio";

const ICONS: Record<ModeResult["mode"], ReactNode> = {
  rgb_only: <Sparkles className="size-4" aria-hidden />,
  user_anchor: <BadgeCheck className="size-4" aria-hidden />,
  lidar: <Radar className="size-4" aria-hidden />,
};

/** Đề xuất tự động và nguồn của bản xác nhận, đọc từ artifact của đúng job. */
export function ModeComparisonView({ jobId }: { jobId: string }) {
  const [data, setData] = useState<ModeComparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getModeComparison(jobId, controller.signal).then(setData, (cause: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(cause, "Không tải được so sánh"));
    });
    return () => controller.abort();
  }, [jobId]);

  if (error) return <Notice tone="rust">{error}</Notice>;
  if (!data) {
    return (
      <p className="flex items-center gap-2 p-6 text-sm text-ink-muted" role="status">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tính so sánh…
      </p>
    );
  }
  const diff = data.difference;
  return (
    <div className="size-full overflow-y-auto bg-paper p-4 sm:p-6">
      <h2 className="text-lg font-bold tracking-tight text-ink">Số đo & nguồn tỉ lệ mét</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Xem tỉ lệ được ước lượng từ đâu và kết quả nào đã được xác nhận để dùng cho scene.
      </p>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        {data.modes.map((mode) => (
          <ModeCard key={mode.mode} mode={mode} />
        ))}
      </div>
      {diff ? (
        <Card className="mt-4 p-4 text-sm">
          <h3 className="font-bold text-ink">Kết quả đã xác nhận so với LiDAR</h3>
          <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
            <Row label="Chênh tỉ lệ" value={`${diff.scale_diff_percent.toFixed(2)} %`} />
            <Row label="Góc lệch mặt sàn" value={`${diff.floor_tilt_deg.toFixed(2)}°`} />
            <Row label="Chênh độ cao camera trung bình" value={`${(diff.camera_height_diff_m * 100).toFixed(1)} cm`} />
            {diff.check_segment_error_m !== null && diff.check_segment_user_m !== null && diff.check_segment_lidar_m !== null && (
              <Row
                label="Đoạn kiểm C–D"
                value={`${diff.check_segment_user_m.toFixed(3)} m so với ${diff.check_segment_lidar_m.toFixed(3)} m (lệch ${(diff.check_segment_error_m * 100).toFixed(1)} cm)`}
              />
            )}
          </dl>
          {data.lidar_ground_truth_assisted && (
            <p className="mt-2 text-xs text-ink-subtle">
              LiDAR của bộ dữ liệu mẫu được căn theo quỹ đạo chuẩn, chỉ để tham khảo, không phải đánh giá độ chính xác.
            </p>
          )}
        </Card>
      ) : (
        <Notice className="mt-4">Chưa đủ kết quả đã xác nhận và LiDAR để so sánh độ lệch.</Notice>
      )}
    </div>
  );
}

function ModeCard({ mode }: { mode: ModeResult }) {
  return (
    <Card className="flex flex-col gap-2 p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-bold text-ink">
          {ICONS[mode.mode]}
          {mode.title}
        </h3>
        {mode.status === "estimated" && <Badge tone="ochre">Ước lượng</Badge>}
        {mode.status === "confirmed" && <Badge tone="sage">Đã xác nhận</Badge>}
        {(mode.status === "missing" || mode.status === "mock") && <Badge tone="neutral">{mode.mode === "rgb_only" ? "Chưa có đề xuất" : "Chưa có"}</Badge>}
        {mode.status === "measured" && <Badge tone="sage">Đã đo</Badge>}
      </div>
      <p className="text-sm text-ink-muted">{mode.status === "mock" ? "Scene này chưa có đề xuất tỉ lệ tự động." : mode.note}</p>
      {["estimated", "confirmed", "measured"].includes(mode.status) && mode.scale_m_per_sfm_unit !== null && (
        <dl className="mt-auto space-y-1 border-t border-line pt-2 text-sm">
          <Row label="Tỉ lệ" value={`${mode.scale_m_per_sfm_unit.toPrecision(5)} m/đơn vị`} />
          {mode.relative_uncertainty != null && (
            <Row label="Độ bất định ước tính" value={`±${(mode.relative_uncertainty * 100).toFixed(1)}%`} />
          )}
          {mode.frames_used != null && <Row label="Số ảnh dùng" value={String(mode.frames_used)} />}
          {mode.camera_height_mean_m !== null && (
            <Row
              label="Độ cao camera"
              value={`${mode.camera_height_mean_m.toFixed(3)} m${mode.camera_height_range_m ? ` (${mode.camera_height_range_m[0].toFixed(2)}–${mode.camera_height_range_m[1].toFixed(2)})` : ""}`}
            />
          )}
        </dl>
      )}
      {mode.mode === "rgb_only" && mode.relative_uncertainty != null && (
        <p className="text-xs text-ink-subtle">Độ bất định phản ánh dao động giữa các ảnh, chưa bao gồm sai lệch có hệ thống của mô hình.</p>
      )}
      {mode.steps.length > 0 && (
        <details className="border-t border-line pt-2 text-xs text-ink-muted">
          <summary className="cursor-pointer font-medium">Cách ước lượng</summary>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            {mode.steps.map((step) => <li key={step}>{step}</li>)}
          </ol>
        </details>
      )}
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-right font-mono text-ink">{value}</dd>
    </div>
  );
}
