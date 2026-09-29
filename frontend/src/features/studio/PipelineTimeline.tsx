"use client";

import { AlertTriangle, Check, Circle, CircleSlash, Hand, Loader2 } from "lucide-react";

import { ProgressBar, formatDuration } from "@/components/studio/primitives";
import { MVP_STAGES, type StageMeta } from "@/features/studio/stages";
import { cn } from "@/lib/cn";
import type { StageId } from "@/lib/contracts/api";
import type { StageState } from "@/lib/contracts/studio";

export interface StageView {
  stage_id: StageId;
  state: StageState;
  /** Thời gian đã chạy (đang chạy) hoặc thời lượng thật (đã xong); null = không đo được. */
  seconds: number | null;
  /** 0..1 chỉ khi đo được thật (vd. phát lại demo); null → dải chạy không số. */
  fraction: number | null;
  error?: { human_message: string; error_code: string } | null;
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
}: {
  stages: readonly StageView[];
  timeNote?: string;
  /** Danh sách stage hiển thị; mặc định 5 stage tới preview (video mẫu). */
  stageList?: readonly StageMeta[];
}) {
  const done = stages.filter((stage) => stage.state === "succeeded").length;
  return (
    <div>
      <div className="mb-5 flex items-baseline justify-between gap-4">
        <p className="text-sm font-medium text-ink">
          {done}/{stageList.length} bước hoàn tất
        </p>
        {timeNote && <p className="text-xs text-ink-subtle">{timeNote}</p>}
      </div>
      <ProgressBar value={done / stageList.length} label="Tổng tiến trình" className="mb-6" />
      <ol className="space-y-1" aria-live="polite">
        {stageList.map((meta) => {
          const stage = stages.find((item) => item.stage_id === meta.id);
          const state = stage?.state ?? "pending";
          const Icon = ICONS[state];
          return (
            <li
              key={meta.id}
              className={cn(
                "rounded-xl px-3 py-3 transition-colors duration-300",
                state === "running" && "bg-ember-soft/60",
                state === "waiting" && "bg-ember-soft/40 ring-1 ring-ember/40",
                state === "failed" && "bg-rust-soft",
              )}
            >
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full",
                    state === "succeeded" && "bg-ink text-paper",
                    state === "running" && "bg-ember-strong text-white",
                    state === "waiting" && "bg-paper-raised text-ember-strong ring-2 ring-ember",
                    state === "failed" && "bg-rust text-white",
                    (state === "pending" || state === "cancelled") && "text-ink-subtle",
                  )}
                >
                  <Icon className={cn("size-3.5", state === "running" && "animate-spin motion-reduce:animate-none")} aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className={cn("text-sm font-medium", state === "pending" ? "text-ink-subtle" : "text-ink")}>
                      {meta.title}
                      <span className="sr-only"> — {STATE_LABEL[state]}</span>
                    </p>
                    {stage?.seconds != null && state !== "pending" && (
                      <span className="shrink-0 text-xs tabular-nums text-ink-subtle">{formatDuration(stage.seconds)}</span>
                    )}
                  </div>
                  {(state === "running" || state === "failed" || state === "waiting") && (
                    <p className="mt-1 text-sm leading-relaxed text-ink-muted">{meta.description}</p>
                  )}
                  {state === "waiting" && (
                    <p className="mt-2 text-xs font-medium tracking-wide text-ember-strong uppercase">Đang chờ bạn</p>
                  )}
                  {state === "running" && (
                    <ProgressBar value={stage?.fraction ?? null} label={`Tiến trình ${meta.title}`} className="mt-3" />
                  )}
                  {state === "failed" && stage?.error && (
                    <p className="mt-2 text-sm text-rust">
                      {stage.error.human_message}{" "}
                      <span className="font-mono text-xs opacity-80">({stage.error.error_code})</span>
                    </p>
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
