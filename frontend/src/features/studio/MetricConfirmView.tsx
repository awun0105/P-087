"use client";

import { Check, Loader2, Radar, Redo2, Ruler, Sparkles, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button, Notice } from "@/components/studio/primitives";
import {
  METRIC_POINT_COUNT,
  METRIC_POINT_LABELS,
  metricInput,
  nextPointHint,
  segments,
} from "@/features/studio/metric";
import { EMPTY_INSPECTION, type InspectionState } from "@/features/viewer/inspection-history";
import { PlayCanvasScene, usePlayCanvasCapability } from "@/features/viewer/PlayCanvasScene";
import type { SplatInspection } from "@/features/viewer/splat-inspection";
import { confirmMetric, getDemoPoints, getMetricAssist, measureOnLidar, previewMetric } from "@/lib/api/studio";
import type { LidarMeasurements, MetricInput, MetricPreview } from "@/lib/contracts/studio";

/**
 * Bước xác nhận tỉ lệ mét (REC-06) sau khi xem 3DGS: chọn A/B (vật biết kích thước),
 * C/D (vật khác để kiểm), 3 điểm sàn → xem trước → xác nhận. Scene dựng từ dataset mẫu
 * có LiDAR thì khoảng cách lấy từ LiDAR, chỉ đọc (ADR 0004 §6); video người dùng nhập tay.
 * Điểm lấy trong hệ gốc file 3DGS; tính toán và bản ghi xác nhận thuộc backend.
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
  const [lidarAvailable, setLidarAvailable] = useState<boolean | null>(null);
  const [lidar, setLidar] = useState<{ points: InspectionState["points"]; result: LidarMeasurements | null; error: string | null } | null>(null);
  const [typed, setTyped] = useState({ anchor: "", check: "" });
  const [preview, setPreview] = useState<{ input: MetricInput; result: MetricPreview } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demoRunning, setDemoRunning] = useState(false);
  const timers = useRef<number[]>([]);
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  useEffect(() => () => timers.current.forEach((timer) => window.clearTimeout(timer)), []);
  const onReady = useCallback((next: SplatInspection | null) => {
    setController(next);
    next?.setMeasuring(true);
  }, []);

  useEffect(() => {
    let alive = true;
    void getMetricAssist(jobId).then((assist) => {
      if (alive) setLidarAvailable(assist.lidar_available);
    });
    return () => {
      alive = false;
    };
  }, [jobId]);

  // Dataset có LiDAR: đủ A–D thì đo ngay trên LiDAR; đổi điểm thì đo lại.
  const pairs = segments(inspection.points);
  const pairKey = pairs ? JSON.stringify(pairs) : null;
  useEffect(() => {
    if (!lidarAvailable || !pairs || pairKey === null) return;
    const controllerAbort = new AbortController();
    const points = inspection.points;
    measureOnLidar(jobId, pairs[0], pairs[1], controllerAbort.signal).then(
      (result) => setLidar({ points, result, error: null }),
      (cause: unknown) => {
        if (!controllerAbort.signal.aborted) {
          setLidar({ points, result: null, error: cause instanceof Error ? cause.message : "Không đo được trên LiDAR" });
        }
      },
    );
    return () => controllerAbort.abort();
    // pairKey đại diện cho `pairs`; tránh đo lại khi chỉ đổi điểm sàn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, lidarAvailable, pairKey]);

  const lidarResult = lidar && pairKey !== null && JSON.stringify(segments(lidar.points)) === pairKey ? lidar : null;
  const source = lidarAvailable ? "lidar_demo" : "user_measured";
  const anchorDistance = lidarAvailable ? String(lidarResult?.result?.anchor.distance_m ?? "") : typed.anchor;
  const checkDistance = lidarAvailable ? String(lidarResult?.result?.check.distance_m ?? "") : typed.check;
  const input = metricInput(inspection.points, anchorDistance, checkDistance, source);
  // Bản xem trước chỉ còn hiệu lực khi điểm và khoảng cách không đổi.
  const current = preview && input && JSON.stringify(preview.input) === JSON.stringify(input) ? preview.result : null;
  const hint = nextPointHint(inspection.points.length);
  // Nút bị khóa phải nói rõ vì sao, không để người dùng đoán.
  const blockedReason = input
    ? null
    : inspection.points.length < METRIC_POINT_COUNT
      ? `Cần chọn đủ ${METRIC_POINT_COUNT} điểm (đã chọn ${inspection.points.length}).`
      : lidarAvailable
        ? lidarResult?.error
          ? "Chưa có số đo LiDAR: chọn lại điểm bị báo lỗi ở trên."
          : "Đang chờ số đo LiDAR…"
        : "Nhập khoảng cách thật của A–B và C–D (mét).";

  /** Dataset mẫu: lấy 7 điểm tự chọn từ LiDAR rồi vẽ lần lượt từng điểm, xong tự xem trước. */
  async function runDemo() {
    if (!controller) return;
    setError(null);
    setDemoRunning(true);
    setPreview(null);
    try {
      const selection = await getDemoPoints(jobId);
      controller.setMeasuring(false);
      timers.current.forEach((timer) => window.clearTimeout(timer));
      timers.current = selection.points.map((_, index) =>
        window.setTimeout(() => {
          controller.setPoints(selection.points.slice(0, index + 1));
          if (index === selection.points.length - 1) {
            setDemoRunning(false);
            const demoInput = metricInput(
              selection.points,
              String(selection.measurements.anchor.distance_m),
              String(selection.measurements.check.distance_m),
              "lidar_demo",
            );
            if (demoInput) {
              void run(async () => {
                setPreview({ input: demoInput, result: await previewMetric(jobId, demoInput) });
              });
            }
          }
        }, 450 * (index + 1)),
      );
    } catch (cause) {
      setDemoRunning(false);
      setError(cause instanceof Error ? cause.message : "Không tự chọn được điểm");
    }
  }

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
          <p className="grid size-full place-items-center p-6 text-center text-sm text-ink/80" role="alert">
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
          Scene dựng từ video chưa có đơn vị mét. Chọn hai đầu một vật biết kích thước (A, B), hai đầu một vật khác để
          kiểm (C, D), rồi 3 điểm trên mặt sàn. Sàn sẽ thành mặt z = 0, A là gốc tọa độ.
        </p>
        {lidarAvailable && (
          <Notice tone="ochre" icon={<Radar aria-hidden />}>
            Scene từ dataset mẫu có LiDAR: khoảng cách lấy từ LiDAR để mô phỏng số đo ngoài đời. Video của bạn sẽ cần nhập
            số đo thật.
          </Notice>
        )}

        {lidarAvailable && (
          <Button className="w-full" disabled={!controller || demoRunning || busy} onClick={() => void runDemo()}>
            {demoRunning ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <Sparkles aria-hidden />}
            {demoRunning ? "Đang chọn điểm trên LiDAR…" : "Tự chọn điểm (demo LiDAR)"}
          </Button>
        )}

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
          <Button
            variant="secondary"
            size="sm"
            aria-label="Làm lại"
            disabled={!inspection.canRedo || inspection.busy}
            onClick={() => controller?.redo()}
          >
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
              <span className="font-mono">{inspection.points[index]?.map((value) => value.toFixed(3)).join(", ") ?? "—"}</span>
            </li>
          ))}
        </ol>

        {lidarAvailable ? (
          <div className="space-y-1 rounded-xl border border-line p-3 text-sm" aria-live="polite">
            <p className="font-medium text-ink">Số đo từ LiDAR</p>
            {!pairs && <p className="text-xs text-ink-subtle">Chọn đủ A, B, C, D để đo.</p>}
            {pairs && !lidarResult && (
              <p className="flex items-center gap-2 text-xs text-ink-muted">
                <Loader2 className="size-3 animate-spin motion-reduce:animate-none" aria-hidden /> Đang đo trên LiDAR…
              </p>
            )}
            {lidarResult?.error && <Notice tone="rust">{lidarResult.error}</Notice>}
            {lidarResult?.result && (
              <>
                <p>
                  A–B: <span className="font-mono">{lidarResult.result.anchor.distance_m.toFixed(3)} m</span>
                </p>
                <p>
                  C–D: <span className="font-mono">{lidarResult.result.check.distance_m.toFixed(3)} m</span>
                </p>
                {[...lidarResult.result.anchor.point_sources, ...lidarResult.result.check.point_sources].includes(
                  "trajectory_alignment",
                ) && (
                  <p className="text-xs text-ochre">
                    Một số điểm nằm ngoài vùng LiDAR phủ: dùng vị trí quy đổi mét theo căn chỉnh quỹ đạo (sai lệch ~7 cm).
                  </p>
                )}
                <p className="text-xs text-ink-subtle">
                  Điểm bắt vào LiDAR cách chỗ click tối đa{" "}
                  {(
                    Math.max(...lidarResult.result.anchor.snap_offsets_m, ...lidarResult.result.check.snap_offsets_m) * 100
                  ).toFixed(1)}{" "}
                  cm.
                </p>
              </>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <DistanceField label="Khoảng cách thật A–B (mét)" value={typed.anchor} onChange={(anchor) => setTyped({ ...typed, anchor })} />
            <DistanceField label="Khoảng cách thật C–D (mét)" value={typed.check} onChange={(check) => setTyped({ ...typed, check })} />
          </div>
        )}

        <Button
          variant="secondary"
          className="w-full"
          disabled={!input || busy || lidarAvailable === null}
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
        {blockedReason && <p className="-mt-2 text-xs text-ink-subtle">{blockedReason}</p>}

        {current && (
          <div className="space-y-2 rounded-xl border border-line p-3 text-sm">
            <p>
              Tỉ lệ: <span className="font-mono">{current.scale_m_per_sfm_unit.toPrecision(5)}</span> m/đơn vị
            </p>
            <p>
              Độ cao camera: {current.camera_height_min_m.toFixed(2)}–{current.camera_height_max_m.toFixed(2)} m
            </p>
            <p>Độ lệch 3 điểm sàn: {(current.floor_residual_m * 100).toFixed(1)} cm</p>
            <p className={current.check_passed ? "text-sage" : "text-rust"}>
              Kiểm C–D: đo được {current.check_measured_m.toFixed(3)} m, lệch {(current.check_error_m * 100).toFixed(1)} cm
              (ngưỡng {(current.check_tolerance_m * 100).toFixed(1)} cm) — {current.check_passed ? "đạt" : "không đạt"}
            </p>
            {current.warnings.map((warning) => (
              <Notice key={warning} tone="ochre">
                {warning}
              </Notice>
            ))}
            <Button
              className="w-full"
              disabled={busy || !input || !current.check_passed}
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
          Điểm lấy từ độ sâu Gaussian, có thể lệch ở vùng mờ. Kiểm độ cao camera và kết quả C–D trước khi xác nhận.
        </p>
      </aside>
    </div>
  );
}

function DistanceField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block text-sm text-ink">
      {label}
      <input
        type="text"
        inputMode="decimal"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="vd 0,90"
        className="mt-1 block w-full rounded-lg border border-line-strong bg-paper px-3 py-2 text-sm"
      />
    </label>
  );
}
