/**
 * Loại đầu vào Studio (ADR 0004). Đuôi file chỉ để lọc sớm ở trình duyệt; loại thật do
 * máy chủ nhận diện theo nội dung và trả trong `UploadRecord.input_kind`.
 */
import type { InputKind, UploadRecord } from "@/lib/contracts/studio";

export const UPLOAD_ACCEPT = ".mp4,.mov,.ply,.sog,.zip,video/mp4,video/quicktime,application/zip,application/x-sog";
export const VIDEO_ACCEPT = ".mp4,.mov,video/mp4,video/quicktime";
export const GAUSSIAN_ACCEPT = ".ply,.sog,.zip,application/zip,application/x-sog";
/** Gói LiDAR luôn là một file ZIP (ADR 0009). */
export const LIDAR_ACCEPT = ".zip,application/zip";

const ACCEPTED_NAME = /\.(mp4|mov|ply|sog|zip)$/i;

export const INPUT_KIND_LABELS: Record<InputKind, string> = {
  rgb_video: "Video",
  gaussian_ply: "Scene 3DGS (.ply)",
  gaussian_ply_colmap: "3DGS + COLMAP (.zip)",
  gaussian_sog: "Scene 3DGS (.sog)",
  registered_lidar: "Gói LiDAR: đám mây đã đăng ký (.zip)",
  lidar_scan_sequence: "Gói LiDAR: scan thô + quỹ đạo (.zip)",
};

/** Lọc sớm theo đuôi; null khi hợp lệ, ngược lại là lời nhắc cho người dùng. */
export function rejectFileName(name: string): string | null {
  return ACCEPTED_NAME.test(name) ? null : "Chỉ nhận video .mp4/.mov, scene 3DGS .ply/.sog hoặc .zip (PLY 3DGS + model COLMAP).";
}

/** Lọc sớm theo nhánh UX; kết quả nhận diện của máy chủ vẫn là authority cuối cùng. */
export function rejectFileNameFor(name: string, kind: "video" | "gaussian" | "lidar"): string | null {
  if (kind === "lidar") return /\.zip$/i.test(name) ? null : "Gói LiDAR là một file .zip gồm đám mây hoặc scan, quỹ đạo, calibration và thời điểm frame.";
  if (kind === "video") return /\.(mp4|mov)$/i.test(name) ? null : "Dựng từ video chỉ nhận .mp4/.mov. Chọn Mở 3DGS để tải .ply/.sog/.zip.";
  return /\.(ply|sog|zip)$/i.test(name) ? null : "Mở 3DGS chỉ nhận .ply, .sog hoặc .zip có PLY. Chọn Dựng từ video cho .mp4/.mov.";
}

/** Record cũ (trước ADR 0004) không có `input_kind` là video. */
export function inputKind(record: UploadRecord): InputKind {
  return record.input_kind ?? "rgb_video";
}

/** LiDAR đi kèm video (ADR 0009), không tự tạo scene và không phải scene 3DGS. */
export function isLidar(record: UploadRecord): boolean {
  const kind = inputKind(record);
  return kind === "registered_lidar" || kind === "lidar_scan_sequence";
}

/** File mở được ở nhánh "Mở 3DGS". */
export function isGaussian(record: UploadRecord): boolean {
  const kind = inputKind(record);
  return kind === "gaussian_ply" || kind === "gaussian_ply_colmap" || kind === "gaussian_sog";
}

/** Chỉ video RGB được dựng scene; chờ server xác minh receipt nếu upload đã chuẩn hóa. */
export function canCreateScene(record: UploadRecord): boolean {
  return inputKind(record) === "rgb_video" && record.video_preparation_status !== "pending";
}

/** Tóm tắt bằng chứng nhận diện để người dùng thấy máy chủ đã hiểu file thế nào. */
export function describeDetection(record: UploadRecord): string {
  const kind = inputKind(record);
  const lidar = record.detection?.lidar;
  if (kind === "registered_lidar" && lidar?.point_count) {
    return `${INPUT_KIND_LABELS[kind]} · ${lidar.point_count.toLocaleString("vi-VN")} điểm · ${lidar.pose_count.toLocaleString("vi-VN")} pose`;
  }
  if (kind === "lidar_scan_sequence" && lidar?.scan_count) {
    return `${INPUT_KIND_LABELS[kind]} · ${lidar.scan_count.toLocaleString("vi-VN")} scan · ${lidar.pose_count.toLocaleString("vi-VN")} pose`;
  }
  const gaussian = record.detection?.gaussian ?? record.detection?.sog;
  if (kind === "rgb_video" || !gaussian) return INPUT_KIND_LABELS[kind];
  const count = gaussian.gaussian_count.toLocaleString("vi-VN");
  return `${INPUT_KIND_LABELS[kind]} · ${count} Gaussian · SH bậc ${gaussian.sh_degree}`;
}
