/**
 * Mô tả hiển thị cho 5 stage của lát cắt MVP (khớp `MVP_PIPELINE` ở backend).
 * Chỉ là copy UI; trạng thái thật luôn lấy từ API tiến trình.
 */

import type { StageId } from "@/lib/contracts/api";

export interface StageMeta {
  id: StageId;
  title: string;
  short: string;
  description: string;
}

export const MVP_STAGES: readonly StageMeta[] = [
  {
    id: "ST-INPUT-VALIDATE",
    title: "Kiểm tra video",
    short: "Kiểm tra",
    description: "Giải mã toàn bộ video, đo độ nhòe và chuyển động của camera trước khi chạy tác vụ nặng.",
  },
  {
    id: "ST-PRIVACY-GATE",
    title: "Quyền riêng tư",
    short: "Riêng tư",
    description: "Ghi nhận xác nhận của người tải lên: video không chứa khuôn mặt hoặc biển số chưa làm mờ.",
  },
  {
    id: "ST-FRAME-EXTRACT",
    title: "Tách khung hình",
    short: "Tách frame",
    description: "Tách video thành ảnh, giữ frame đủ nét và lấy mẫu đều để dựng 3D.",
  },
  {
    id: "ST-CAMERA-POSE",
    title: "Ước lượng camera",
    short: "Camera",
    description: "COLMAP tìm điểm đặc trưng chung giữa các ảnh để tính vị trí và hướng camera.",
  },
  {
    id: "ST-VISUAL-RECON",
    title: "Dựng 3D Gaussian Splatting",
    short: "Dựng 3DGS",
    description: "Brush huấn luyện hàng trăm nghìn Gaussian trên GPU để tái tạo cảnh nhìn được từ mọi góc.",
  },
] as const;

export function stageMeta(id: StageId): StageMeta | undefined {
  return MVP_STAGES.find((stage) => stage.id === id);
}
