import type { StageId } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";
import {
  LIDAR_CALIBRATION_QA_STAGE,
  LIDAR_ODOMETRY_STAGE,
  LIDAR_STAGE,
  STUDIO_STAGES,
  type StageMeta,
} from "@/features/studio/stages";
import { demoSceneHref } from "@/lib/api/demo-session";

/**
 * Stage có trang inspection: các stage của job cùng các bước LiDAR động. Bước của pipeline thống nhất (xem bản che,
 * duyệt vật, Tạo mesh, chuẩn bị LOD) không phải stage của job nên không có trang này; mở chúng chỉ ra "chưa hoàn tất".
 */
const INSPECTABLE_STAGES: readonly StageMeta[] = [...STUDIO_STAGES, LIDAR_STAGE, LIDAR_ODOMETRY_STAGE, LIDAR_CALIBRATION_QA_STAGE];

/** Route chỉ nhận stage Studio đã có nội dung inspection, gồm các bước LiDAR động. */
export function inspectionStage(value: string): StageMeta | undefined {
  return INSPECTABLE_STAGES.find((stage) => stage.id === value);
}

export function inspectHref(jobId: string, stageId: StageId): string {
  return demoSceneHref(stageId) ?? `/scenes/${encodeURIComponent(jobId)}/stages/${encodeURIComponent(stageId)}`;
}

export function progressHref(jobId: string): string {
  return demoSceneHref(null) ?? `/scenes/${encodeURIComponent(jobId)}?tab=progress`;
}

/** Cả timeline lẫn route trực tiếp đều dùng trạng thái attempt từ API. */
export function canInspect(progress: JobProgress, stageId: StageId): boolean {
  return progress.stages.some((stage) =>
    stage.stage_id === stageId &&
    (stage.state === "succeeded" || (stageId === LIDAR_CALIBRATION_QA_STAGE.id && stage.state === "failed"))
  );
}
