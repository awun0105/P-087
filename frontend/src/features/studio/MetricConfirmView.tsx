"use client";

import { Check, Loader2, Redo2, Ruler, Undo2, X } from "lucide-react";
import { useCallback, useState } from "react";

import { Button, Notice } from "@/components/studio/primitives";
import { METRIC_POINT_COUNT, METRIC_POINT_LABELS, metricInput, nextPointHint } from "@/features/studio/metric";
import { EMPTY_INSPECTION, type InspectionState } from "@/features/viewer/inspection-history";
import { PlayCanvasScene, usePlayCanvasCapability } from "@/features/viewer/PlayCanvasScene";
import type { SplatInspection } from "@/features/viewer/splat-inspection";
import { confirmMetric, previewMetric } from "@/lib/api/studio";
import type { MetricInput, MetricPreview } from "@/lib/contracts/studio";

/**
 * Bước xác nhận tỉ lệ mét (REC-06) sau khi xem 3DGS: chọn A/B trên vật biết kích
 * thước, 3 điểm sàn, nhập khoảng cách thật → xem trước số liệu → xác nhận. Điểm lấy
 * trong hệ gốc file 3DGS; tính toán và bản ghi xác nhận thuộc backend.
 */
export function MetricConfirmView({
  jobId,
  contentUrl,
  filename,
  onClose,
  onConfirmed,
}: {
  jobId: string;
  contentUrl: string;
  filename: string;
  onClose: () => void;
  onConfirmed: () => void;
}) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const [controller, setController] = useState<SplatInspection | null>(null);
  const [inspection, setInspection] = useState<InspectionState>(EMPTY_INSPECTION);
  const [distance, setDistance] = useState("");
  const [preview, setPreview] = useState<{ input: MetricInput; result: MetricPreview } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const onReady = useCallback((next: SplatInspection | null) => {
    setController(next);
    next?.setMeasuring(true);
  }, []);

  const input = metricInput(inspection.points, distance);
  // Bản xem trước chỉ còn hiệu lực khi điểm và khoảng cách không đổi.
  const current = preview && input && JSON.stringify(preview.input) === JSON.stringify(input) ? preview.result : null;
  const hint = nextPointHint(inspection.points.length);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Thao tác thất bại");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid size-full lg:grid-cols-[1fr_22rem]">
      <div className="relative min-h-80 bg-viewport">
        {capability === "failed" || capability === "unavailable" ? (
          <p className="grid size-full place-items-center p-6 text-center text-sm text-paper/80" role="alert">
            Không render được 3DGS để chọn điểm: trình duyệt cần WebGL2 hoặc WebGPU.
          </p>
        ) : (
          <PlayCanvasScene
            contentUrl={contentUrl}
            contentFilename={filename}
            renderer="webgl"
            mode="VISUAL"
            capability={capability}
            onFailed={fail}
            enableInspection
            inspectionMaxPoints={METRIC_POINT_COUNT}
            onInspectionReady={onReady}
            onInspectionState={setInspection}
          />
        )}
      </div>
      <aside
        className="space-y-4 overflow-y-auto border-l border-line bg-paper-raised p-4"
        aria-label="Xác nhận tỉ lệ mét"
        onFocusCapture={() => controller?.setFormFocused(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) controller?.setFormFocused(false);
        }}
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
            <Ruler className="size-4" aria-hidden />
            Xác nhận tỉ lệ mét
          </h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Đóng">
            <X aria-hidden />
          </Button>
        </div>
        <p className="text-xs leading-relaxed text-ink-muted">
          Scene dựng từ video chưa có đơn vị mét. Chọn hai đầu một vật bạn biết kích thước thật, rồi 3 điểm trên mặt sàn.
          Sàn sẽ thành mặt z = 0, A là gốc tọa độ.
        </p>

        <div className="flex flex-wrap gap-2">
          <Button
            variant={inspection.measuring ? "primary" : "secondary"}
            size="sm"
            disabled={!controller || inspection.busy}
            onClick={() => controller?.setMeasuring(!inspection.measuring)}
          >
            {inspection.measuring ? "Đang chọn điểm" : "Xoay/di chuyển camera"}
          </Button>
          <Button variant="secondary" size="sm" disabled={!inspection.canUndo || inspection.busy} onClick={() => controller?.undo()}>
            <Undo2 aria-hidden />
            Hoàn tác
          </Button>
          <Button variant="secondary" size="sm" disabled={!inspection.canRedo || inspection.busy} onClick={() => controller?.redo()}>
            <Redo2 aria-hidden />
          </Button>
        </div>
        {hint && inspection.measuring && <p className="text-sm text-ember-strong">{hint}</p>}
        {!inspection.measuring && <p className="text-xs text-ink-subtle">Bấm “Đang chọn điểm” để quay lại chọn.</p>}
        {inspection.error && <Notice tone="rust">{inspection.error}</Notice>}

        <ol className="space-y-1 text-xs text-ink-muted">
          {METRIC_POINT_LABELS.map((label, index) => (
            <li key={label} className="flex gap-2">
              <span className="w-12 font-medium text-ink">{label}</span>
              <span className="font-mono">
                {inspection.points[index]?.map((value) => value.toFixed(3)).join(", ") ?? "—"}
              </span>
            </li>
          ))}
        </ol>

        <label className="block text-sm text-ink">
          Khoảng cách thật A–B (mét)
          <input
            type="text"
            inputMode="decimal"
            value={distance}
            onChange={(event) => setDistance(event.target.value)}
            placeholder="vd 0,90"
            className="mt-1 block w-full rounded-lg border border-line-strong bg-paper px-3 py-2 text-sm"
          />
        </label>

        <Button
          variant="secondary"
          className="w-full"
          disabled={!input || busy}
          onClick={() =>
            input &&
            void run(async () => {
              setPreview({ input, result: await previewMetric(jobId, input) });
            })
          }
        >
          {busy && !current ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : null}
          Xem trước
        </Button>

        {current && (
          <div className="space-y-2 rounded-xl border border-line p-3 text-sm">
            <p>
              Tỉ lệ: <span className="font-mono">{current.scale_m_per_sfm_unit.toPrecision(5)}</span> m/đơn vị
            </p>
            <p>
              Độ cao camera: {current.camera_height_min_m.toFixed(2)}–{current.camera_height_max_m.toFixed(2)} m
            </p>
            <p>Độ lệch 3 điểm sàn: {(current.floor_residual_m * 100).toFixed(1)} cm</p>
            {current.warnings.map((warning) => (
              <Notice key={warning} tone="ochre">
                {warning}
              </Notice>
            ))}
            <Button
              className="w-full"
              disabled={busy || !input}
              onClick={() =>
                input &&
                void run(async () => {
                  await confirmMetric(jobId, input, current.preview_checksum);
                  onConfirmed();
                })
              }
            >
              <Check aria-hidden />
              Xác nhận tỉ lệ này
            </Button>
          </div>
        )}
        {error && <Notice tone="rust">{error}</Notice>}
        <p className="text-xs text-ink-subtle">
          Điểm lấy từ độ sâu Gaussian, có thể lệch ở vùng mờ. Kiểm độ cao camera có hợp lý không trước khi xác nhận.
        </p>
      </aside>
    </div>
  );
}
