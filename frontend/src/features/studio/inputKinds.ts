/**
 * Loại đầu vào Studio (ADR 0004). Đuôi file chỉ để lọc sớm ở trình duyệt; loại thật do
 * máy chủ nhận diện theo nội dung và trả trong `UploadRecord.input_kind`.
 */
import type { InputKind, UploadRecord } from "@/lib/contracts/studio";

export const UPLOAD_ACCEPT = ".mp4,.mov,.ply,.zip,video/mp4,video/quicktime,application/zip";

const ACCEPTED_NAME = /\.(mp4|mov|ply|zip)$/i;

export const INPUT_KIND_LABELS: Record<InputKind, string> = {
  rgb_video: "Video",
  gaussian_ply: "Scene 3DGS (.ply)",
  gaussian_ply_colmap: "3DGS + COLMAP (.zip)",
};

/** Lọc sớm theo đuôi; null khi hợp lệ, ngược lại là lời nhắc cho người dùng. */
export function rejectFileName(name: string): string | null {
  return ACCEPTED_NAME.test(name) ? null : "Chỉ nhận video .mp4/.mov, scene 3DGS .ply hoặc .zip (PLY 3DGS + model COLMAP).";
}

/** Record cũ (trước ADR 0004) không có `input_kind` là video. */
export function inputKind(record: UploadRecord): InputKind {
  return record.input_kind ?? "rgb_video";
}

/** Hiện chỉ video có luồng dựng scene; import 3DGS là gói 5 của plan tổng thể. */
export function canCreateScene(record: UploadRecord): boolean {
  return inputKind(record) === "rgb_video";
}

/** Tóm tắt bằng chứng nhận diện để người dùng thấy máy chủ đã hiểu file thế nào. */
export function describeDetection(record: UploadRecord): string {
  const kind = inputKind(record);
  const gaussian = record.detection?.gaussian;
  if (kind === "rgb_video" || !gaussian) return INPUT_KIND_LABELS[kind];
  const count = gaussian.gaussian_count.toLocaleString("vi-VN");
  return `${INPUT_KIND_LABELS[kind]} · ${count} Gaussian · SH bậc ${gaussian.sh_degree}`;
}
