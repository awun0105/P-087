/**
 * Mô tả hiển thị các stage. `MVP_STAGES` = 5 stage tới preview 3DGS (khớp `MVP_PIPELINE`,
 * dùng cho video mẫu); `STUDIO_STAGES` thêm bước xác nhận tỉ lệ mét (khớp
 * `STUDIO_PIPELINE`, dùng cho job thật). Chỉ là copy UI; trạng thái thật lấy từ API.
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

/** REC-06: COLMAP/Brush không biết 1 đơn vị là bao nhiêu mét — người dùng cho một khoảng cách thật. */
export const METRIC_STAGE: StageMeta = {
  id: "ST-METRIC-CANONICALIZE",
  title: "Xác nhận tỉ lệ mét",
  short: "Tỉ lệ mét",
  description:
    "Chọn hai điểm A, B trên scene (vd hai mép lối đi) và nhập khoảng cách thật; hệ thống quy đổi cả scene sang mét để dùng cho mô phỏng.",
};

export const STUDIO_STAGES: readonly StageMeta[] = [...MVP_STAGES, METRIC_STAGE];

export function stageMeta(id: StageId): StageMeta | undefined {
  return STUDIO_STAGES.find((stage) => stage.id === id);
}
