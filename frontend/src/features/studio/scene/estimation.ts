import type { StageView } from "@/features/studio/PipelineTimeline";

export interface PipelineEta {
  /** Thời gian còn lại ước tính của giai đoạn đang chạy (giây) */
  currentStageRemainingSeconds: number | null;
  /** Tổng thời gian còn lại ước tính của các bước máy đang và sẽ tự động xử lý (giây) */
  totalRemainingSeconds: number | null;
  /** Tên định dạng ngắn gọn (vd: "~8 phút 20 giây") */
  formattedRemaining: string | null;
}

/** Chỉ suy thời gian stage hiện tại từ elapsed time và fraction đo được. */
export function estimateRemainingTime(
  stages: readonly StageView[],
  isStale?: boolean,
): PipelineEta {
  const runningStage = stages.find((s) => s.state === "running");
  const elapsed = runningStage?.seconds;
  const fraction = runningStage?.fraction;
  if (
    !runningStage || isStale || elapsed === null || elapsed === undefined || !Number.isFinite(elapsed) || elapsed <= 0 ||
    fraction === null || fraction === undefined || !Number.isFinite(fraction) || fraction <= 0 || fraction >= 1
  ) {
    return {
      currentStageRemainingSeconds: null,
      totalRemainingSeconds: null,
      formattedRemaining: null,
    };
  }

  const runningIndex = stages.findIndex((s) => s.stage_id === runningStage.stage_id);
  const currentRemaining = Math.ceil((elapsed / fraction) * (1 - fraction));
  if (!Number.isFinite(currentRemaining) || currentRemaining <= 0) {
    return {
      currentStageRemainingSeconds: null,
      totalRemainingSeconds: null,
      formattedRemaining: null,
    };
  }
  const hasUnfinishedFutureStage = stages.slice(runningIndex + 1).some((stage) => stage.state !== "succeeded");
  const totalRemaining = hasUnfinishedFutureStage ? null : currentRemaining;

  return {
    currentStageRemainingSeconds: currentRemaining,
    totalRemainingSeconds: totalRemaining,
    formattedRemaining: totalRemaining === null ? null : formatEtaDuration(totalRemaining),
  };
}

/**
 * Định dạng thời gian ước tính còn lại:
 * Vd: "~45 giây", "~8 phút 30 giây", "~1 giờ 15 phút"
 */
export function formatEtaDuration(seconds: number): string {
  const total = Math.max(1, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;

  if (hours > 0) {
    return `~${hours} giờ ${minutes > 0 ? `${minutes} phút` : ""}`.trim();
  }
  if (minutes > 0) {
    return `~${minutes} phút ${rest > 0 ? `${rest} giây` : ""}`.trim();
  }
  return `~${rest} giây`;
}
