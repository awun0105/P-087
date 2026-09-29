import type { JobManifest } from "@/lib/contracts/api";
import { stageMeta } from "@/features/studio/stages";

export type SceneStatusTone = "neutral" | "ember" | "sage" | "ochre" | "rust";

export interface SceneStatusView {
  label: string;
  tone: SceneStatusTone;
  active: boolean;
}

/**
 * Nhãn trạng thái scene cho người dùng. Preview sẵn sàng thì scene "Sẵn sàng"
 * dù job vẫn RUNNING ở bước xác nhận tỉ lệ mét (chưa thuộc Studio MVP).
 */
export function sceneStatus(job: JobManifest | null, previewReady: boolean): SceneStatusView {
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
