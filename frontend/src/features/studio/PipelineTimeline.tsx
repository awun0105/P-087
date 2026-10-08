"use client";

import { AlertTriangle, Check, Circle, CircleSlash, Hand, Loader2 } from "lucide-react";
import { useState } from "react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";

import { ProgressBar } from "@/components/studio/primitives";
import { LIDAR_CALIBRATION_QA_STAGE, MVP_STAGES, type StageMeta } from "@/features/studio/stages";
import { inspectHref, inspectionStage } from "@/features/studio/inspection";
import { guidanceFor } from "@/features/studio/errorGuidance";
import { cn } from "@/lib/cn";
import type { ExecutionError, StageId } from "@/lib/contracts/api";
import type { StageState } from "@/lib/contracts/studio";
import { formatDuration } from "@/lib/format";
import { estimateRemainingTime, formatEtaDuration } from "@/features/studio/scene/estimation";

export interface StageView {
  stage_id: StageId;
  state: StageState;
  /** Thời gian đã chạy (đang chạy) hoặc thời lượng thật (đã xong); null = không đo được. */
  seconds: number | null;
  /** 0..1 chỉ khi đo được thật (vd. phát lại demo); null → dải chạy không số. */
  fraction: number | null;
  error?: ExecutionError | null;
}

const ICONS: Record<StageState, typeof Check> = {
  pending: Circle,
  running: Loader2,
  waiting: Hand,
  succeeded: Check,
  failed: AlertTriangle,
  cancelled: CircleSlash,
};

/**
 * Danh sách stage dọc. Tổng tiến trình tính theo số stage đã xong (quan sát được),
 * không quy đổi thời gian thành phần trăm.
 */
export function PipelineTimeline({
  stages,
  timeNote,
  stageList = MVP_STAGES,
  jobId,
  isStale = false,
  selectedStage,
  onSelectStage,
}: {
  stages: readonly StageView[];
  timeNote?: string;
  /** Danh sách stage hiển thị; mặc định 5 stage tới preview (video mẫu). */
  stageList?: readonly StageMeta[];
  /** Mẫu replay không có job nên không tạo link Inspect job giả. */
  jobId?: string;
  /** True nếu job đang RUNNING nhưng heartbeat đã quá hạn (mất kết nối hoặc worker chết). */
  isStale?: boolean;
  selectedStage?: StageId | null;
  onSelectStage?: (stageId: StageId) => void;
}) {
  const [internalSelected, setInternalSelected] = useState<StageId | null>(null);
  const selected = selectedStage !== undefined ? selectedStage : internalSelected;
  const setSelected = onSelectStage
    ? (fn: (prev: StageId | null) => StageId | null) => {
        const next = fn(selected);
        if (next) onSelectStage(next);
      }
    : setInternalSelected;
  const done = stages.filter((stage) => stage.state === "succeeded").length;
  const eta = estimateRemainingTime(stages, isStale);

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-4">
        <div className="flex items-baseline gap-3">
          <p className="text-sm font-medium text-ink">
            {done}/{stageList.length} bước hoàn tất
          </p>
          {isStale && (
            <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-500">
              Mất kết nối tiến trình
            </span>
          )}
          {!isStale && eta.formattedRemaining && (
            <span className="rounded-md bg-paper-sunken px-2 py-0.5 text-xs font-mono text-ink-muted">
              Còn {eta.formattedRemaining}
            </span>
          )}
        </div>
        {timeNote && <p className="text-xs text-ink-subtle">{timeNote}</p>}
      </div>
      <ProgressBar value={done / stageList.length} label="Tổng tiến trình" className="mb-6" />
      <ol className="space-y-1" aria-live="polite">
        {stageList.map((meta) => {
          const stage = stages.find((item) => item.stage_id === meta.id);
          const state = stage?.state ?? "pending";
          const isCurrentStale = state === "running" && isStale;
          const inspectable = state === "succeeded" || (meta.id === LIDAR_CALIBRATION_QA_STAGE.id && state === "failed");
          const Icon = isCurrentStale ? AlertTriangle : ICONS[state];
          return (
            <li
              key={meta.id}
              className={cn(
                "rounded-xl px-3 py-3 transition-colors duration-300",
                state === "running" && !isStale && "bg-ember-soft/60",
                state === "running" && isStale && "bg-amber-500/10 ring-1 ring-amber-500/30",
                state === "waiting" && "bg-ember-soft/40 ring-1 ring-ember/40",
                state === "failed" && "bg-rust-soft",
              )}
            >
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full",
                    state === "succeeded" && "bg-sage text-paper",
                    state === "running" && !isStale && "bg-primary text-primary-foreground",
                    state === "running" && isStale && "bg-amber-500 text-on-accent",
                    state === "waiting" && "bg-paper-raised text-ember-strong ring-2 ring-ember",
                    state === "failed" && "bg-destructive-fill text-on-accent",
                    (state === "pending" || state === "cancelled") && "text-ink-subtle",
                  )}
                >
                  <Icon className={cn("size-3.5", state === "running" && !isStale && "animate-spin motion-reduce:animate-none")} aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className={cn("text-sm font-medium", state === "pending" ? "text-ink-subtle" : "text-ink")}>
                      {(jobId && inspectable) || onSelectStage ? (
                        <button
                          type="button"
                          aria-expanded={selected === meta.id}
                          aria-controls={`stage-detail-${meta.id}`}
                          onClick={() => {
                            if (onSelectStage) {
                              onSelectStage(meta.id);
                            } else {
                              setSelected((value) => (value === meta.id ? null : meta.id));
                            }
                          }}
                          className="cursor-pointer text-left underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ember"
                        >
                          {meta.title}
                          <span className="sr-only"> — xem chi tiết giai đoạn</span>
                        </button>
                      ) : (
                        <>
                          {meta.title}
                          <span className="sr-only"> — {isCurrentStale ? "gián đoạn" : STATE_LABEL[state]}</span>
                        </>
                      )}
                    </p>
                    {stage?.seconds != null && state !== "pending" && (
                      <span className="shrink-0 text-xs value-tech text-ink-subtle">
                        {formatDuration(stage.seconds)}
                        {state === "running" && !isStale && eta.currentStageRemainingSeconds != null && (
                          <span className="ml-1 text-ink-muted">· còn {formatEtaDuration(eta.currentStageRemainingSeconds)}</span>
                        )}
                        {isCurrentStale && (
                          <span className="ml-1 font-medium text-amber-500">· gián đoạn</span>
                        )}
                      </span>
                    )}
                  </div>
                  {isCurrentStale && (
                    <p className="mt-1 text-sm text-amber-500">
                      Tiến trình bị gián đoạn. Bấm thử lại để tiếp tục huấn luyện từ checkpoint đã lưu.
                    </p>
                  )}
                  {!isCurrentStale && (state === "running" || state === "failed" || state === "waiting") && (
                    <p className="mt-1 text-sm leading-relaxed text-ink-muted">{meta.description}</p>
                  )}
                  {state === "waiting" && (
                    <p className="label-tech mt-2 text-ember-strong">Đang chờ bạn</p>
                  )}
                  {state === "running" && !isStale && (
                    <ProgressBar value={stage?.fraction ?? null} label={`Tiến trình ${meta.title}`} className="mt-3" />
                  )}
                  {state === "failed" && stage?.error && (() => {
                    const err = stage.error;
                    const guidance = guidanceFor(err);
                    const cause = guidance?.cause ?? err.human_message;
                    const fix = guidance?.fix;
                    const retryableLabel = err.retryable ? "Có thể thử lại" : "Cần sửa đầu vào trước khi chạy lại";
                    const logExcerpt = Array.isArray(err.details?.log_excerpt)
                      ? err.details.log_excerpt.filter((line): line is string => typeof line === "string")
                      : [];

                    return (
                      <div className="mt-2 space-y-1 text-sm text-rust" role="alert">
                        <p>
                          {cause} <span className="font-mono text-xs opacity-80">({err.error_code})</span>
                        </p>
                        {fix && <p className="text-xs leading-relaxed text-ink-muted">{fix}</p>}
                        <p className="text-xs font-medium text-ink-subtle">{retryableLabel}</p>
                        {logExcerpt.length > 0 && (
                          <details className="mt-2 rounded border border-line bg-paper-sunken p-2 text-xs text-ink">
                            <summary className="cursor-pointer font-medium text-ink-muted hover:text-ink">
                              Chi tiết kỹ thuật
                            </summary>
                            <pre className="mt-2 max-h-60 overflow-x-auto whitespace-pre-wrap font-mono text-xs text-ink-subtle">
                              {logExcerpt.join("\n")}
                            </pre>
                          </details>
                        )}
                      </div>
                    );
                  })()}
                  {jobId && inspectable && selected === meta.id && (
                    <div id={`stage-detail-${meta.id}`} className="mt-3 space-y-2 border-t border-line pt-3">
                      <p className="text-sm leading-relaxed text-ink-muted">{meta.description}</p>
                      {inspectionStage(meta.id) && <Link href={inspectHref(jobId, meta.id)} className="inline-flex rounded-lg bg-ember-soft px-3 py-2 text-sm font-medium text-ember-strong focus-visible:outline-2 focus-visible:outline-ember">Xem giai đoạn</Link>}
                    </div>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

const STATE_LABEL: Record<StageState, string> = {
  pending: "chưa chạy",
  running: "đang chạy",
  waiting: "đang chờ bạn",
  succeeded: "đã xong",
  failed: "lỗi",
  cancelled: "đã hủy",
};
