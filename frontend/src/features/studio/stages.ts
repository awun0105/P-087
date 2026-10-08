/**
 * Mô tả hiển thị các stage. `MVP_STAGES` = 5 stage tới preview 3DGS (khớp `MVP_PIPELINE`,
 * là nhóm preview); `STUDIO_STAGES` thêm bước xác nhận tỉ lệ mét, hình học/collision và
 * tách vật thể (khớp `STUDIO_PIPELINE`, dùng cho job và video mẫu). Trạng thái thật lấy từ API.
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
    "Chọn A, B trên một vật biết kích thước, C, D trên vật khác để kiểm, và 3 điểm sàn; hệ thống quy đổi cả scene sang mét, sàn thành z = 0.",
};

/** REC-06 canonical + REC-05 + REC-10: chạy tự động sau khi xác nhận tỉ lệ. */
export const GEOMETRY_STAGE: StageMeta = {
  id: "ST-RGB-GEOMETRY",
  title: "Hình học & collision",
  short: "Collision",
  description:
    "Quy đổi 3DGS và camera sang mét, dựng collision mesh bằng voxel và khoét không gian cho robot, kiểm lại tỉ lệ bằng đoạn C–D rồi đóng gói bundle cho mô phỏng.",
};

/** ADR 0007 (v2): tách scene thành nền đã vá + từng vật có Gaussian/collider riêng; lỗi 3 lần thì người dùng chọn
 * chạy lại hoặc dùng hộp ứng viên (ADR 0006). Người dùng xác nhận vật sau. */
export const OBJECT_STAGE: StageMeta = {
  id: "ST-OBJECT-EXTRACT",
  title: "Tách vật thể",
  short: "Vật thể",
  description:
    "Tách scene thành nền đã vá và từng vật có hình 3DGS + collider riêng (SAM2 phân đoạn, gán nhãn theo đóng góp render) để bạn xác nhận. Thử tối đa 3 lần; vẫn lỗi thì bạn chọn chạy lại hoặc dùng hộp ứng viên. Máy không có runtime tách theo vật thì dùng hộp.",
};

export const STUDIO_STAGES: readonly StageMeta[] = [...MVP_STAGES, METRIC_STAGE, GEOMETRY_STAGE, OBJECT_STAGE];

/** ADR 0009: chỉ job có gói LiDAR mới có bước nhận và fuse dữ liệu. */
export const LIDAR_STAGE: StageMeta = {
  id: "ST-LIDAR-INGEST",
  title: "Nhận dữ liệu LiDAR",
  short: "LiDAR",
  description:
    "Giải gói LiDAR, ghép các scan theo quỹ đạo thành một đám mây đã đăng ký (nếu nộp scan thô), kiểm quỹ đạo, calibration và tìm mặt sàn.",
};

export const LIDAR_CALIBRATION_QA_STAGE: StageMeta = {
  id: "ST-LIDAR-CALIBRATION-QA",
  title: "QA calibration LiDAR",
  short: "QA LiDAR",
  description:
    "So khớp scan LiDAR theo pose với cạnh ảnh RGB, lưu overlay và chẩn đoán. Báo cáo chưa chứng minh calibration đạt chuẩn sản xuất hoặc đủ điều kiện làm collision source.",
};

/** Danh sách stage của một job theo các stage API trả: job có gói LiDAR có thêm bước LiDAR sau bước tách frame. */
export function stagesFor(stageIds: readonly StageId[]): readonly StageMeta[] {
  if (!stageIds.includes(LIDAR_STAGE.id)) return STUDIO_STAGES;
  const index = STUDIO_STAGES.findIndex((stage) => stage.id === "ST-FRAME-EXTRACT") + 1;
  const lidarStages = stageIds.includes(LIDAR_CALIBRATION_QA_STAGE.id)
    ? [LIDAR_STAGE, LIDAR_CALIBRATION_QA_STAGE]
    : [LIDAR_STAGE];
  return [...STUDIO_STAGES.slice(0, index), ...lidarStages, ...STUDIO_STAGES.slice(index)];
}

export function stageMeta(id: StageId): StageMeta | undefined {
  if (id === LIDAR_STAGE.id) return LIDAR_STAGE;
  if (id === LIDAR_CALIBRATION_QA_STAGE.id) return LIDAR_CALIBRATION_QA_STAGE;
  return STUDIO_STAGES.find((stage) => stage.id === id);
}
