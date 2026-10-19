import type { JobManifest, JobStatus, StageId } from "@/lib/contracts/api";
import type { JobProgress, SceneSummary } from "@/lib/contracts/studio";
import { stageMeta } from "@/features/studio/stages";
import type { GeometryStep } from "@/features/studio/scene/useObjectify";

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
export function sceneStatus(
  job: JobManifest | null,
  previewReady: boolean,
  awaitingReview = false,
  awaitingObjectChoice = false,
  geometryReview: GeometryReview | null = null,
): SceneStatusView {
  if (job === null) return { label: "Chưa xử lý", tone: "neutral", active: false, group: "idle" };
  if (awaitingReview) return { label: "Cần xem bản đã che", tone: "ochre", active: false, group: "action" };
  if (awaitingObjectChoice && job.status === "SUCCEEDED") return OBJECT_CHOICE_STATUS;
  if (geometryReview && job.status === "SUCCEEDED") return GEOMETRY_STATUS[geometryReview];
  const confirmed = job.stage_artifacts.some((item) => item.stage_id === "ST-METRIC-CANONICALIZE");
  return deriveStatus(job.status, job.current_stage, job.current_stage === "ST-METRIC-CANONICALIZE" && previewReady && !confirmed);
}

const OBJECT_CHOICE_STATUS: SceneStatusView = { label: "Cần chọn cách tách vật thể", tone: "ochre", active: false, group: "action" };

/** Bước "Duyệt vật & Tạo mesh" (T-021): job đã xong nhưng scene còn việc. Dùng chung cho danh sách và đầu trang scene. */
type GeometryReview = NonNullable<SceneSummary["geometry_review"]>;
const GEOMETRY_STATUS: Record<GeometryReview, SceneStatusView> = {
  running: { label: "Đang tạo mesh", tone: "ember", active: true, group: "running" },
  failed: { label: "Tạo mesh lỗi", tone: "rust", active: false, group: "action" },
  waiting: { label: "Chờ duyệt vật", tone: "ochre", active: false, group: "action" },
};

/** Trạng thái của một thẻ ở danh sách Scenes/Tổng quan: gom mọi điều danh sách biết về scene. */
export function sceneSummaryStatus(scene: SceneSummary): SceneStatusView {
  return sceneStatus(
    scene.latest_job,
    scene.preview_ready,
    scene.awaiting_anonymization_review,
    scene.awaiting_object_choice,
    scene.geometry_review ?? null,
  );
}

/**
 * Câu báo cho job chờ GPU đúng runtime (T-040). Job đã có stage không tự chạy tiếp trên máy khác:
 * phiên bản công cụ có thể đã đổi, khi đó job cần chạy lại từ đầu.
 */
export function runtimeWaitText(progress: JobProgress): string {
  const started = progress.stages.some((stage) => stage.state === "succeeded" || stage.state === "running" || stage.state === "failed");
  return started
    ? "Chưa có máy đúng phiên bản công cụ của job đang chạy. Nếu phiên bản đã đổi, job này cần chạy lại từ đầu."
    : "Đang chờ GPU: chưa có máy xử lý nào đang chạy đúng phiên bản công cụ của job này. Job tự chạy khi máy đó lên.";
}

/**
 * Header scene đọc progress thật; cùng bảng nhãn với Scenes/Jobs, không suy DONE từ preview. `geometry` là hàng
 * "Duyệt vật & Tạo mesh" (T-021): job đã xong nhưng scene Draft thì header phải nói còn việc phải làm.
 */
export function progressSceneStatus(progress: JobProgress, awaitingObjectChoice = false, geometry: GeometryStep | null = null): SceneStatusView {
  if (progress.waiting_for === "resources") return { label: "Đang chờ tài nguyên", tone: "ochre", active: true, group: "running" };
  // T-040: chưa có GPU worker nào đang sống chạy đúng phiên bản công cụ của job; job tự chạy khi máy đó lên.
  if (progress.waiting_for === "runtime") return { label: "Đang chờ GPU", tone: "ochre", active: true, group: "running" };
  // Frame đã che xong, pipeline dừng chờ người upload xem — không phải worker đang chạy hay đang xếp hàng.
  if (progress.waiting_for === "anonymization_review") return { label: "Cần xem bản đã che", tone: "ochre", active: false, group: "action" };
  if (awaitingObjectChoice && progress.status === "SUCCEEDED") return OBJECT_CHOICE_STATUS;
  if (geometry && progress.status === "SUCCEEDED" && (geometry.state === "running" || geometry.state === "failed" || geometry.state === "waiting")) {
    return GEOMETRY_STATUS[geometry.state];
  }
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
