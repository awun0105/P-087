import type { StageId } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";
import { LIDAR_CALIBRATION_QA_STAGE, stageMeta } from "@/features/studio/stages";

/** Route chỉ nhận stage Studio đã có nội dung inspection, gồm các bước LiDAR động. */
export function inspectionStage(value: string) {
  return stageMeta(value as StageId);
}

export function inspectHref(jobId: string, stageId: StageId): string {
  return `/scenes/${encodeURIComponent(jobId)}/stages/${encodeURIComponent(stageId)}`;
}

export function progressHref(jobId: string): string {
  return `/scenes/${encodeURIComponent(jobId)}?tab=progress`;
}

/** Cả timeline lẫn route trực tiếp đều dùng trạng thái attempt từ API. */
export function canInspect(progress: JobProgress, stageId: StageId): boolean {
  return progress.stages.some((stage) =>
    stage.stage_id === stageId &&
    (stage.state === "succeeded" || (stageId === LIDAR_CALIBRATION_QA_STAGE.id && stage.state === "failed"))
  );
}
