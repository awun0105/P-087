"use client";

import { Check, Loader2, Radar } from "lucide-react";
import { useEffect, useState } from "react";

import { notifySuccess } from "@/components/studio/feedback";
import { Button, Notice } from "@/components/studio/primitives";
import { confirmMetric, previewMetric } from "@/lib/api/studio";
import type { MetricInput, MetricPreview, MetricProposal } from "@/lib/contracts/studio";
import { errorMessage } from "@/lib/ui-error";

/** Đề xuất từ gói LiDAR có đủ sàn và hai đoạn thì thành đúng đầu vào của bước xác nhận; thiếu thì không dùng được. */
export function lidarMetricInput(proposal: MetricProposal): MetricInput | null {
  if (!proposal.floor || !proposal.segments) return null;
  const { segments } = proposal;
  return {
    floor_points: proposal.floor.points,
    point_a: segments.point_a,
    point_b: segments.point_b,
    distance_m: segments.distance_m,
    check_a: segments.check_a,
    check_b: segments.check_b,
    check_distance_m: segments.check_distance_m,
    distance_source: "lidar_trajectory",
  };
}

const centimetres = (metres: number) => `${(metres * 100).toFixed(0)} cm`;

/**
 * Xác nhận tỉ lệ mét cho job có gói LiDAR (ADR 0009): **không chọn điểm**. Tỉ lệ và mặt sàn đã
 * được tính từ quỹ đạo LiDAR; người dùng xem scene bám quỹ đạo tới đâu (số frame khớp, độ lệch pose) rồi bấm một nút.
 * Quyết định vẫn là của người dùng: độ lệch lớn nghĩa là quỹ đạo, calibration hoặc video không khớp nhau.
 */
export function LidarMetricConfirm({ jobId, proposal, onConfirmed }: { jobId: string; proposal: MetricProposal; onConfirmed: () => void }) {
  const input = lidarMetricInput(proposal);
  const alignment = proposal.alignment ?? null;
  const [preview, setPreview] = useState<MetricPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = input ? JSON.stringify(input) : null;

  useEffect(() => {
    if (!input) return;
    let alive = true;
    previewMetric(jobId, input).then(
      (result) => { if (alive) setPreview(result); },
      (cause: unknown) => { if (alive) setError(errorMessage(cause, "Không tính được tỉ lệ từ LiDAR")); },
    );
    return () => { alive = false; };
    // `key` đại diện cho `input` (đối tượng mới mỗi lần render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, key]);

  async function confirm() {
    if (!input || !preview) return;
    setBusy(true);
    setError(null);
    try {
      await confirmMetric(jobId, input, preview.preview_checksum);
      notifySuccess("Đã xác nhận tỉ lệ từ LiDAR. Hệ thống đang tiếp tục dựng hình học.");
      onConfirmed();
    } catch (cause) {
      setError(errorMessage(cause, "Không xác nhận được tỉ lệ"));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4" data-testid="lidar-metric-confirm">
      <Notice tone="ochre" icon={<Radar aria-hidden />}>
        Scene này có gói LiDAR nên tỉ lệ mét và mặt sàn lấy từ quỹ đạo LiDAR. Bạn không cần chọn điểm; xem các số dưới
        đây rồi xác nhận.
      </Notice>
      {alignment && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-xl border border-line p-3 text-sm">
          <dt className="text-ink-muted">Frame khớp</dt>
          <dd>{alignment.registered_frames}/{alignment.input_frames}</dd>
          <dt className="text-ink-muted">Pose lệch quỹ đạo</dt>
          <dd>trung vị {centimetres(alignment.offset_median_m)} · lớn nhất {centimetres(alignment.offset_max_m)}</dd>
          <dt className="text-ink-muted">Đường đi camera</dt>
          <dd>{alignment.path_length_m.toFixed(1)} m</dd>
          <dt className="text-ink-muted">Tỉ lệ</dt>
          <dd>{proposal.scale_m_per_sfm_unit.toFixed(4)} m/đơn vị</dd>
          <dt className="text-ink-muted">Quỹ đạo</dt>
          <dd className="font-sans">{alignment.trajectory_origin === "ground_truth" ? "Quỹ đạo chuẩn của dataset" : "Người nộp tự tính"}</dd>
        </dl>
      )}
      {!input && <Notice tone="rust">Gói LiDAR không cho ra mặt sàn hoặc đoạn kiểm; không xác nhận tự động được.</Notice>}
      {input && !preview && !error && (
        <p className="flex items-center gap-2 text-sm text-ink-muted" role="status">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tính tỉ lệ từ LiDAR…
        </p>
      )}
      {preview && (
        <div className="space-y-2 rounded-xl border border-line p-3 text-sm">
          <p>
            Độ cao camera trên sàn: <span className="font-mono">{preview.camera_height_min_m.toFixed(2)}–{preview.camera_height_max_m.toFixed(2)} m</span>
          </p>
          {preview.warnings.map((warning) => (
            <Notice key={warning} tone="ochre">{warning}</Notice>
          ))}
          <Button className="w-full" disabled={busy || !preview.check_passed} onClick={() => void confirm()}>
            <Check aria-hidden /> Xác nhận tỉ lệ từ LiDAR
          </Button>
        </div>
      )}
      {error && <Notice tone="rust">{error}</Notice>}
      <p className="text-xs text-ink-subtle">
        Độ lệch pose lớn (vài chục cm trở lên) thường do quỹ đạo, calibration hoặc video không thuộc cùng một lượt quay.
        Khi đó đừng xác nhận; kiểm lại gói LiDAR rồi tạo scene mới.
      </p>
    </div>
  );
}
