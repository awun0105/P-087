"use client";

import { errorMessage } from "@/lib/ui-error";

import { FlaskConical, Loader2, Radar, Ruler } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Badge, Card, Notice } from "@/components/studio/primitives";
import { getModeComparison } from "@/lib/api/studio";
import type { ModeComparison, ModeResult } from "@/lib/contracts/studio";

const ICONS: Record<ModeResult["mode"], ReactNode> = {
  rgb_only: <FlaskConical className="size-4" aria-hidden />,
  user_anchor: <Ruler className="size-4" aria-hidden />,
  lidar: <Radar className="size-4" aria-hidden />,
};

/**
 * Demo 3 hướng tỉ lệ trên cùng scene (ADR 0004 §5): RGB only (mô phỏng, không số),
 * anchor người dùng, LiDAR. Số liệu do backend tính từ artifact thật của scene.
 */
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
      <h2 className="text-lg font-bold tracking-tight text-ink">So sánh 3 hướng khôi phục tỉ lệ</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Cùng video, cùng camera; khác nhau ở cách biết 1 đơn vị 3DGS dài bao nhiêu mét và mặt sàn nằm đâu.
      </p>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        {data.modes.map((mode) => (
          <ModeCard key={mode.mode} mode={mode} />
        ))}
      </div>
      {diff ? (
        <Card className="mt-4 p-4 text-sm">
          <h3 className="font-bold text-ink">Anchor người dùng so với LiDAR</h3>
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
              LiDAR của dataset được căn theo quỹ đạo ground-truth (GT-assisted): dùng làm tham chiếu demo, không phải
              đánh giá độ chính xác RGB-only độc lập.
            </p>
          )}
        </Card>
      ) : (
        <Notice className="mt-4">Cần cả anchor người dùng và LiDAR để tính độ lệch giữa hai hướng.</Notice>
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
        {mode.status === "mock" && <Badge tone="ochre">Mô phỏng · P1</Badge>}
        {mode.status === "missing" && <Badge tone="neutral">Chưa có</Badge>}
        {mode.status === "measured" && <Badge tone="sage">Đã đo</Badge>}
      </div>
      <p className="text-xs text-ink-muted">{mode.note}</p>
      {mode.steps.length > 0 && (
        <ol className="list-decimal space-y-1 pl-5 text-xs text-ink-muted">
          {mode.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      )}
      {mode.status === "measured" && mode.scale_m_per_sfm_unit !== null && (
        <dl className="mt-auto space-y-1 border-t border-line pt-2 text-sm">
          <Row label="Tỉ lệ" value={`${mode.scale_m_per_sfm_unit.toPrecision(5)} m/đơn vị`} />
          {mode.camera_height_mean_m !== null && (
            <Row
              label="Độ cao camera"
              value={`${mode.camera_height_mean_m.toFixed(3)} m${mode.camera_height_range_m ? ` (${mode.camera_height_range_m[0].toFixed(2)}–${mode.camera_height_range_m[1].toFixed(2)})` : ""}`}
            />
          )}
        </dl>
      )}
      {mode.status === "mock" && <p className="mt-auto border-t border-line pt-2 text-sm text-ink-subtle">Tỉ lệ ước lượng: chưa triển khai</p>}
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
