"use client";

import { Download } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ErrorFeedback } from "@/components/studio/feedback";
import { buttonVariants, Notice } from "@/components/studio/primitives";
import { DATA_SOURCE_LABEL, BenchmarkTable } from "@/features/studio/value/BenchmarkTable";
import { benchmarkMetricsUrl, getBenchmarkMetrics, type BenchmarkResponse, type BenchmarkSummary } from "@/lib/api/value";
import { errorMessage } from "@/lib/ui-error";

const ALL = "all";
const EMPTY_STATE = "Chưa có scene nào được đưa vào benchmark. Bật 'Đưa vào benchmark' trong panel Benchmark của scene.";

function median(value: number | null, unit = "phút"): string {
  return value === null ? "chưa đo được" : `${value.toFixed(1)} ${unit}`;
}

function Tile({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-paper px-3 py-2">
      <p className="text-xs text-ink-subtle">{label}</p>
      <p className="mt-0.5 text-base font-semibold text-ink">{children}</p>
    </div>
  );
}

/** Ô tổng hợp của bộ benchmark: cùng các ô của sổ kết quả Playbook. */
export function BenchmarkSummaryTiles({ summary }: { summary: BenchmarkSummary }) {
  const gpus = Object.entries(summary.machine_median_minutes_by_gpu);
  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
      <Tile label="Số scene">{summary.scenes}</Tile>
      <Tile label={`Người (trung vị, n = ${summary.hands_on_n})`}>{median(summary.hands_on_median_minutes)}</Tile>
      <Tile label="Máy (trung vị theo GPU)">
        {gpus.length === 0
          ? "chưa đo được"
          : gpus.map(([gpu, value]) => `${gpu}: ${median(value)}`).join(" · ")}
      </Tile>
      <Tile label="Khe khớp / bỏ sót / giả">
        {summary.gaps_total === 0
          ? "chưa đo được"
          : `${summary.gaps_agree_total}/${summary.gaps_total} · ${summary.missed_total} · ${summary.false_total}`}
      </Tile>
      <Tile label="Đạt từ L2 / L3">{`${summary.scenes_at_least_l2} / ${summary.scenes_at_least_l3}`}</Tile>
      <Tile label={`Làm tay (trung vị, n = ${summary.manual_n})`}>{median(summary.manual_median_minutes)}</Tile>
    </div>
  );
}

function useBenchmark() {
  const [state, setState] = useState<{ data: BenchmarkResponse | null; error: string | null }>({ data: null, error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getBenchmarkMetrics(controller.signal)
      .then((data) => { if (!controller.signal.aborted) setState({ data, error: null }); })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setState({ data: null, error: errorMessage(cause) }); });
    return () => controller.abort();
  }, [attempt]);
  return { ...state, retry: () => setAttempt((value) => value + 1) };
}

/** Trang /benchmark: bảng nhiều scene, lọc theo nguồn dữ liệu, tải CSV/Markdown của cả bộ (link thật tới API). */
export function BenchmarkPage() {
  const { data, error, retry } = useBenchmark();
  const [source, setSource] = useState(ALL);
  const rows = useMemo(() => {
    if (!data) return [];
    return source === ALL ? data.rows : data.rows.filter((row) => row.data_source === source);
  }, [data, source]);

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Benchmark giá trị</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-muted">
            Mỗi dòng là lần chạy mới nhất của một scene trong benchmark. Số chưa đo được ghi là chưa có, không phải 0.
          </p>
        </div>
        {data && (
          <div className="flex shrink-0 flex-wrap gap-2">
            <a href={benchmarkMetricsUrl("csv")} download className={buttonVariants({ variant: "secondary", size: "sm" })}>
              <Download aria-hidden /> Tải CSV
            </a>
            <a href={benchmarkMetricsUrl("md")} download className={buttonVariants({ variant: "secondary", size: "sm" })}>
              <Download aria-hidden /> Tải Markdown
            </a>
          </div>
        )}
      </header>

      {error && <ErrorFeedback message={`Không tải được benchmark: ${error}`} retry={retry} />}
      {!data && !error && <p role="status" className="text-sm text-ink-muted">Đang tải benchmark…</p>}

      {data && data.rows.length === 0 && <Notice>{EMPTY_STATE}</Notice>}

      {data && data.rows.length > 0 && (
        <>
          <BenchmarkSummaryTiles summary={data.summary} />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor="benchmark-source" className="text-ink-muted">Nguồn dữ liệu</label>
            <select
              id="benchmark-source"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              className="rounded-md border border-line bg-paper px-2 py-1"
            >
              <option value={ALL}>Tất cả</option>
              {Object.entries(DATA_SOURCE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
          {rows.length === 0 ? (
            <Notice>Không có scene nào thuộc nguồn này.</Notice>
          ) : (
            <BenchmarkTable rows={rows} />
          )}
        </>
      )}
    </div>
  );
}
