import type { JobManifest, JobStatus, StageId } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";
import { stageMeta } from "@/features/studio/stages";

export type SceneStatusTone = "neutral" | "ember" | "sage" | "ochre" | "rust";

/** Nhóm dùng để lọc danh sách (Scenes, Jobs). */
export type SceneStatusGroup = "running" | "action" | "done" | "failed" | "idle";

export interface SceneStatusView {
  label: string;
  tone: SceneStatusTone;
  /** Còn thay đổi mà không cần người dùng (poll nhanh hơn). */
  active: boolean;
  group: SceneStatusGroup;
}

/**
 * Bảng nhãn trạng thái dùng chung cho Scenes, Jobs và header (STUDIO_UX_SPEC.md D-12).
 *
 * Không có nhãn "Sẵn sàng" chung: có preview không có nghĩa là sẵn sàng mô phỏng. Nhãn chỉ nói
 * điều danh sách biết chắc từ JobManifest; trạng thái vật thể/gói/duyệt nằm trong màn scene.
 */
export function sceneStatus(job: JobManifest | null, previewReady: boolean): SceneStatusView {
  if (job === null) return { label: "Chưa xử lý", tone: "neutral", active: false, group: "idle" };
  const confirmed = job.stage_artifacts.some((item) => item.stage_id === "ST-METRIC-CANONICALIZE");
  return deriveStatus(job.status, job.current_stage, job.current_stage === "ST-METRIC-CANONICALIZE" && previewReady && !confirmed);
}

/** Header scene đọc progress thật; cùng bảng nhãn với Scenes/Jobs, không suy DONE từ preview. */
export function progressSceneStatus(progress: JobProgress): SceneStatusView {
  if (progress.waiting_for === "resources") return { label: "Đang chờ tài nguyên", tone: "ochre", active: true, group: "running" };
  return deriveStatus(progress.status, progress.current_stage, progress.waiting_for === "metric_confirmation");
}

function deriveStatus(status: JobStatus, currentStage: StageId | null, waitingMetric: boolean): SceneStatusView {
  const stage = currentStage ? stageMeta(currentStage) : undefined;
  switch (status) {
    case "QUEUED":
      return { label: "Đang chờ worker", tone: "ochre", active: true, group: "running" };
    case "RUNNING": {
      if (waitingMetric) {
        // Preview xong, pipeline dừng chờ người chọn điểm — không phải worker đang chạy.
        return { label: "Cần xác nhận tỉ lệ", tone: "ochre", active: false, group: "action" };
      }
      if (currentStage === "ST-METRIC-CANONICALIZE" || currentStage === "ST-RGB-GEOMETRY") {
        return { label: "Đang dựng collision", tone: "ember", active: true, group: "running" };
      }
      if (currentStage === "ST-OBJECT-EXTRACT") {
        return { label: "Đang tách vật thể", tone: "ember", active: true, group: "running" };
      }
      return { label: stage ? `Đang chạy · ${stage.short}` : "Đang xử lý", tone: "ember", active: true, group: "running" };
    }
    case "FAILED":
      return { label: stage ? `Lỗi · ${stage.short}` : "Lỗi", tone: "rust", active: false, group: "failed" };
    case "CANCELLED":
      return { label: "Đã huỷ", tone: "neutral", active: false, group: "idle" };
    default:
      // SUCCEEDED: pipeline dựng xong (bundle + vật thể ứng viên). Xác nhận vật/gói/duyệt xem trong scene.
      return { label: "Đã dựng scene", tone: "sage", active: false, group: "done" };
  }
}

export const STATUS_FILTERS: { value: SceneStatusGroup | "all" | "needs_action"; label: string }[] = [
  { value: "all", label: "Tất cả" },
  { value: "needs_action", label: "Cần xử lý" },
  { value: "running", label: "Đang xử lý" },
  { value: "done", label: "Đã dựng" },
];
