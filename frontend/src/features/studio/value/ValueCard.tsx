"use client";

import Link from "next/link";
import { Download } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { ErrorFeedback } from "@/components/studio/feedback";
import { buttonVariants } from "@/components/studio/primitives";
import {
  getValueMetrics,
  valueMetricsUrl,
  type Figure,
  type ValueScorecard,
} from "@/lib/api/value";
import { errorMessage } from "@/lib/ui-error";

/** Nhãn nguồn của một số. Số thiếu dữ liệu là "chưa có", không bao giờ là 0. */
export function sourceLabel(figure: Figure): string {
  if (figure.provenance === "measured") return "đo";
  if (figure.provenance === "declared") return "khai báo";
  return "chưa có";
}

/** P2 luôn là "đo, so với số thước": phần mô phỏng do máy đo, chỉ mốc so sánh do người nhập (không gọi là "khai báo"). */
export function p2Label(p2: ValueScorecard["p2"]): string {
  if (p2.unavailable_reason) return "chưa có";
  if (p2.gaps_checked === 0 && p2.max_distance_error_cm.value === null) return "chưa có";
  return "đo, so với số thước";
}

/** Phần khe của P2. Chưa đo khe nào thì không có số để hiện (không phải 0). */
export function p2GapText(p2: ValueScorecard["p2"]): string | null {
  if (p2.unavailable_reason || p2.gaps_checked === 0) return null;
  return `khe khớp ${p2.gaps_agree}/${p2.gaps_checked} · bỏ sót ${p2.missed_obstacles} · giả ${p2.false_obstacles}`;
}

/** Bậc L4 là khai báo tay; L0–L3 là đo bằng máy. */
export function p4Label(level: ValueScorecard["p4"]["level"]): string {
  return level === 4 ? "khai báo" : "đo";
}

function formatNumber(value: number, digits: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(digits);
}

/** Văn bản của một số: giá trị kèm đơn vị, hoặc "chưa đo được" nếu không có giá trị. */
export function figureText(figure: Figure): string {
  if (figure.value === null) return "chưa đo được";
  if (typeof figure.value === "string") return figure.value;
  if (figure.unit === "USD") return `~$${formatNumber(figure.value, 2)}`;
  const text = formatNumber(figure.value, 1);
  return figure.unit ? `${text} ${figure.unit}` : text;
}

function useValueMetrics(jobId: string, refreshKey: string) {
  const [state, setState] = useState<{ data: ValueScorecard | null; error: string | null }>({ data: null, error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getValueMetrics(jobId, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setState({ data, error: null }); })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setState({ data: null, error: errorMessage(cause) }); });
    return () => controller.abort();
  }, [jobId, refreshKey, attempt]);
  return { ...state, retry: () => setAttempt((value) => value + 1) };
}

function Source({ label }: { label: string }) {
  return <span className="ml-1.5 align-middle text-xs text-ink-subtle">({label})</span>;
}

function Chip({ title, figure }: { title: string; figure: Figure }) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-paper px-3 py-2">
      <p className="text-xs text-ink-subtle">{title}</p>
      <p className="mt-0.5 text-sm font-semibold text-ink">
        {figureText(figure)}
        <Source label={sourceLabel(figure)} />
      </p>
      {figure.value === null && figure.note && <p className="mt-0.5 text-xs text-ink-muted">{figure.note}</p>}
    </div>
  );
}

function P2Cell({ p2 }: { p2: ValueScorecard["p2"] }) {
  const label = p2Label(p2);
  if (p2.unavailable_reason) {
    return (
      <Cell title="P2 · Độ đúng" label={label}>
        <p className="text-sm text-ink-muted">{p2.unavailable_reason}</p>
      </Cell>
    );
  }
  const error = p2.max_distance_error_cm;
  return (
    <Cell title="P2 · Độ đúng" label={label}>
      <p className="text-sm font-semibold text-ink">
        {p2GapText(p2) ?? "chưa có khe kiểm nào được đo"}
      </p>
      {p2GapText(p2) === null && (
        <p className="mt-0.5 text-xs text-ink-muted">Thêm khe và gắn layout trong panel Benchmark của scene.</p>
      )}
      <p className="mt-0.5 text-xs text-ink-muted">
        sai số kích thước tối đa: {error.value === null ? "chưa đo được" : figureText(error)} · vật cản chính có collider {p2.key_obstacles_with_collider}
      </p>
    </Cell>
  );
}

function Cell({ title, label, children }: { title: string; label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-paper px-3 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold text-ink">{title}</h4>
        <span className="text-xs text-ink-subtle">{label}</span>
      </div>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

function P3Cell({ p3 }: { p3: ValueScorecard["p3"] }) {
  const consistency = p3.consistent === null ? "nhất quán: chưa kiểm" : p3.consistent ? "nhất quán: Đạt" : "nhất quán: Không";
  return (
    <Cell title="P3 · Đổi bố trí" label={sourceLabel(p3.edit_to_retest_minutes)}>
      <p className="text-sm font-semibold text-ink">
        đổi→thử {figureText(p3.edit_to_retest_minutes)}
      </p>
      <p className="mt-0.5 text-xs text-ink-muted">{consistency}</p>
      {p3.unavailable_reason && <p className="mt-0.5 text-xs text-ink-muted">{p3.unavailable_reason}</p>}
      {p3.edit_to_retest_minutes.value === null && p3.edit_to_retest_minutes.note && (
        <p className="mt-0.5 text-xs text-ink-muted">{p3.edit_to_retest_minutes.note}</p>
      )}
    </Cell>
  );
}

function P4Cell({ p4 }: { p4: ValueScorecard["p4"] }) {
  return (
    <Cell title="P4 · Bậc sẵn sàng" label={p4Label(p4.level)}>
      <p className="text-sm font-semibold text-ink">L{p4.level}</p>
      {p4.level < 4 && p4.reasons.length > 0 && (
        <>
          <p className="mt-1 text-xs text-ink-muted">Chưa lên bậc tiếp:</p>
          <ul className="mt-0.5 list-disc pl-4 text-xs text-ink-muted">
            {p4.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </>
      )}
    </Cell>
  );
}

/** Thẻ "Giá trị" đầu tab đánh giá: 5 metric của scene, mỗi số có nhãn nguồn; số thiếu dữ liệu ghi rõ lý do. */
export function ValueCard({ jobId, revision }: { jobId: string; revision: string | null }) {
  const { data, error, retry } = useValueMetrics(jobId, revision ?? "");
  const north = data?.north_star;
  return (
    <section aria-labelledby="value-heading" className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="value-heading" className="text-lg font-bold tracking-tight">Giá trị</h3>
          <p className="mt-1 max-w-2xl text-sm text-ink-muted">
            Năm metric của scene theo Playbook. Mỗi số có nhãn nguồn; số chưa đo được được ghi rõ lý do, không phải 0.
          </p>
        </div>
        {data && (
          <div className="flex shrink-0 flex-wrap gap-2">
            <Link href={`/scenes/${encodeURIComponent(jobId)}?tab=studio`} className={buttonVariants({ variant: "secondary", size: "sm" })}>
              Mở Benchmark
            </Link>
            <a href={valueMetricsUrl(jobId, "csv")} download className={buttonVariants({ variant: "secondary", size: "sm" })}>
              <Download aria-hidden /> Tải CSV
            </a>
            <a href={valueMetricsUrl(jobId, "md")} download className={buttonVariants({ variant: "secondary", size: "sm" })}>
              <Download aria-hidden /> Tải Markdown
            </a>
          </div>
        )}
      </div>
      {error && <ErrorFeedback className="mt-4" message={`Không tải được thẻ Giá trị: ${error}`} retry={retry} />}
      {!data && !error && <p role="status" className="mt-4 text-sm text-ink-muted">Đang tính thẻ Giá trị…</p>}
      {data && north && (
        <div className="mt-4 space-y-3">
          <div className="grid gap-2 sm:grid-cols-3">
            <Chip title="Người" figure={north.hands_on_minutes} />
            <div className="min-w-0 rounded-md border border-line bg-paper px-3 py-2">
              <p className="text-xs text-ink-subtle">Máy</p>
              <p className="mt-0.5 text-sm font-semibold text-ink">
                {figureText(north.machine_minutes)}
                <Source label={sourceLabel(north.machine_minutes)} />
                <span className="font-normal text-ink-muted"> trên {String(north.hardware.gpu_name ?? "GPU chưa rõ")}</span>
              </p>
              {north.machine_minutes.value === null && north.machine_minutes.note && (
                <p className="mt-0.5 text-xs text-ink-muted">{north.machine_minutes.note}</p>
              )}
            </div>
            <Chip title="Chi phí" figure={north.cost_usd} />
          </div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            <Cell title="P1 · Can thiệp" label={sourceLabel(north.interventions_total)}>
              <p className="text-sm font-semibold text-ink">
                {north.interventions_total.value === null ? "chưa đo được" : `${north.interventions_total.value} lần`}
              </p>
              <p className="mt-0.5 text-xs text-ink-muted">
                Làm tay: {figureText(data.manual_baseline_minutes)}
                <Source label={sourceLabel(data.manual_baseline_minutes)} />
              </p>
            </Cell>
            <P2Cell p2={data.p2} />
            <P3Cell p3={data.p3} />
            <P4Cell p4={data.p4} />
          </div>
        </div>
      )}
    </section>
  );
}
