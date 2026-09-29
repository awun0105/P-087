import type { JobManifest } from "@/lib/contracts/api";
import { stageMeta } from "@/features/studio/stages";

export type SceneStatusTone = "neutral" | "ember" | "sage" | "ochre" | "rust";

export interface SceneStatusView {
  label: string;
  tone: SceneStatusTone;
  active: boolean;
}

/**
 * Nhãn trạng thái scene cho người dùng. Preview sẵn sàng mà job còn RUNNING ở bước
 * xác nhận tỉ lệ mét (REC-06) nghĩa là đang chờ người dùng, không phải worker đang chạy.
 */
export function sceneStatus(job: JobManifest | null, previewReady: boolean): SceneStatusView {
  if (previewReady && job?.status === "RUNNING" && job.current_stage === "ST-METRIC-CANONICALIZE") {
    return { label: "Chờ xác nhận tỉ lệ", tone: "ochre", active: false };
  }
  if (previewReady) return { label: "Sẵn sàng", tone: "sage", active: false };
  if (job === null) return { label: "Chưa xử lý", tone: "neutral", active: false };
  switch (job.status) {
    case "QUEUED":
      return { label: "Đang chờ worker", tone: "ochre", active: true };
    case "RUNNING": {
      const stage = job.current_stage ? stageMeta(job.current_stage) : undefined;
      return { label: stage ? `Đang chạy · ${stage.short}` : "Đang xử lý", tone: "ember", active: true };
    }
    case "FAILED":
      return { label: "Lỗi", tone: "rust", active: false };
    case "CANCELLED":
      return { label: "Đã hủy", tone: "neutral", active: false };
    default:
      return { label: "Hoàn tất", tone: "sage", active: false };
  }
}
