import type { StageId } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";
import { STUDIO_STAGES } from "@/features/studio/stages";

/** Route chỉ nhận tám stage Studio; không tự mở surface cho stage contract khác. */
export function inspectionStage(value: string) {
  return STUDIO_STAGES.find((stage) => stage.id === value);
}

export function inspectHref(jobId: string, stageId: StageId): string {
  return `/scenes/${encodeURIComponent(jobId)}/stages/${encodeURIComponent(stageId)}`;
}

export function progressHref(jobId: string): string {
  return `/scenes/${encodeURIComponent(jobId)}?tab=progress`;
}

/** Cả timeline lẫn route trực tiếp đều dùng trạng thái attempt từ API. */
export function canInspect(progress: JobProgress, stageId: StageId): boolean {
  return progress.stages.some((stage) => stage.stage_id === stageId && stage.state === "succeeded");
}
