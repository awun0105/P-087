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
    description: "Đọc video và dữ liệu đi kèm, đo độ nét và độ rung.",
  },
  {
    id: "ST-PRIVACY-GATE",
    title: "Quyền riêng tư",
    short: "Riêng tư",
    description: "Ghi nhận cam kết của người tải lên về dữ liệu.",
  },
  {
    id: "ST-FRAME-EXTRACT",
    title: "Tách khung hình",
    short: "Tách ảnh",
    description: "Tách video thành ảnh và giữ ảnh đủ nét. Nếu bật che mặt và biển số, hệ thống che rồi chờ bạn xem lại.",
  },
  {
    id: "ST-CAMERA-POSE",
    title: "Ước lượng camera",
    short: "Camera",
    description: "Tìm vị trí và hướng máy quay ở từng ảnh.",
  },
  {
    id: "ST-VISUAL-RECON",
    title: "Dựng 3D Gaussian Splatting",
    short: "Dựng 3DGS",
    description: "Dựng cảnh 3D xem được từ mọi góc.",
  },
] as const;

/** REC-06: COLMAP/Brush không biết 1 đơn vị là bao nhiêu mét — người dùng cho một khoảng cách thật. */
export const METRIC_STAGE: StageMeta = {
  id: "ST-METRIC-CANONICALIZE",
  title: "Xác nhận tỉ lệ mét",
  short: "Tỉ lệ mét",
  description: "Chấp nhận tỉ lệ hệ thống đề xuất hoặc tự nhập một khoảng cách thật, rồi chọn mặt sàn.",
};

/** REC-06 canonical + REC-05 + REC-10: chạy tự động sau khi xác nhận tỉ lệ. */
export const GEOMETRY_STAGE: StageMeta = {
  id: "ST-RGB-GEOMETRY",
  title: "Collision môi trường",
  short: "Collision",
  description: "Dựng lưới va chạm để robot không đi xuyên tường và sàn.",
};

/** ADR 0007 (v2): tách scene thành nền đã vá + từng vật có Gaussian/collider riêng; lỗi 3 lần thì người dùng chọn
 * chạy lại hoặc dùng hộp ứng viên (ADR 0006). Người dùng xác nhận vật sau. */
export const OBJECT_STAGE: StageMeta = {
  id: "ST-OBJECT-EXTRACT",
  title: "Tách vật thể",
  short: "Vật thể",
  description: "Tách cảnh thành từng vật ứng viên để bạn duyệt.",
};

/** Id chỉ có ở giao diện (không có trong contracts/StageId): hàng ảo "Duyệt vật & Tạo mesh" (T-021). */
export const GEOMETRY_REVIEW_STAGE_ID = "UI-GEOMETRY-REVIEW" as const;

/** Id của một hàng trên timeline: stage thật của API, hoặc hàng ảo phía giao diện. */
export type TimelineStageId = StageId | typeof GEOMETRY_REVIEW_STAGE_ID;

export interface TimelineStageMeta extends Omit<StageMeta, "id"> {
  id: TimelineStageId;
}

/** Hàng ảo sau "Tách vật thể": không có route inspect, trạng thái lấy từ `ObjectifyState` (xem `geometryReviewStep`). */
export const GEOMETRY_REVIEW_STAGE: TimelineStageMeta = {
  id: GEOMETRY_REVIEW_STAGE_ID,
  title: "Duyệt vật & Tạo mesh",
  short: "Tạo mesh",
  description: "Xác nhận vật, sửa vùng nếu cần, rồi bấm Tạo mesh. Xong bước này mới đi bộ (Walk) và xuất gói được.",
};

export const STUDIO_STAGES: readonly StageMeta[] = [...MVP_STAGES, METRIC_STAGE, GEOMETRY_STAGE, OBJECT_STAGE];

/** ADR 0009: chỉ job có gói LiDAR mới có bước nhận và fuse dữ liệu. */
export const LIDAR_STAGE: StageMeta = {
  id: "ST-LIDAR-INGEST",
  title: "Nhận dữ liệu LiDAR",
  short: "LiDAR",
  description: "Đọc gói LiDAR, ghép các lượt quét và tìm mặt sàn.",
};

export const LIDAR_ODOMETRY_STAGE: StageMeta = {
  id: "ST-LIDAR-ODOMETRY",
  title: "Ước lượng quỹ đạo LiDAR",
  short: "Quỹ đạo",
  description: "Ước lượng đường đi của cảm biến từ các lượt quét LiDAR.",
};

export const LIDAR_CALIBRATION_QA_STAGE: StageMeta = {
  id: "ST-LIDAR-CALIBRATION-QA",
  title: "Kiểm tra căn chỉnh LiDAR",
  short: "Khớp LiDAR",
  description: "Chồng điểm LiDAR lên ảnh màu để xem hai nguồn có khớp nhau không.",
};

/** Danh sách stage của một job theo các stage API trả: job có gói LiDAR có thêm bước LiDAR sau bước tách frame. */
export function stagesFor(stageIds: readonly StageId[]): readonly StageMeta[] {
  if (stageIds.includes(LIDAR_ODOMETRY_STAGE.id)) {
    const index = STUDIO_STAGES.findIndex((stage) => stage.id === "ST-FRAME-EXTRACT") + 1;
    return [...STUDIO_STAGES.slice(0, index), LIDAR_ODOMETRY_STAGE, ...STUDIO_STAGES.slice(index)];
  }
  if (!stageIds.includes(LIDAR_STAGE.id)) return STUDIO_STAGES;
  const index = STUDIO_STAGES.findIndex((stage) => stage.id === "ST-FRAME-EXTRACT") + 1;
  const lidarStages = stageIds.includes(LIDAR_CALIBRATION_QA_STAGE.id)
    ? [LIDAR_STAGE, LIDAR_CALIBRATION_QA_STAGE]
    : [LIDAR_STAGE];
  return [...STUDIO_STAGES.slice(0, index), ...lidarStages, ...STUDIO_STAGES.slice(index)];
}

/** Bước người dùng xem bản đã che (T-061); có khi job chọn che khuôn mặt / biển số. */
export const ANONYMIZATION_REVIEW_STAGE: StageMeta = {
  id: "ST-ANONYMIZATION-REVIEW",
  title: "Xem bản đã che",
  short: "Xem bản che",
  description: "Xem lại ảnh đã che khuôn mặt và biển số rồi xác nhận để dựng 3D.",
};

/** Bước người dùng duyệt vật trước khi Tạo mesh (T-061). */
export const OBJECT_CONFIRM_STAGE: StageMeta = {
  id: "ST-OBJECT-CONFIRM",
  title: "Duyệt vật",
  short: "Duyệt vật",
  description: "Xác nhận hoặc bỏ qua từng vật, sửa vùng nếu cần, rồi bấm Tạo mesh.",
};

/** Bước hệ thống Tạo mesh và lưới va chạm từng vật (T-061). */
export const SCENE_DECOMPOSE_STAGE: StageMeta = {
  id: "ST-SCENE-DECOMPOSE",
  title: "Tạo mesh và lưới va chạm từng vật",
  short: "Tạo mesh",
  description: "Dựng bề mặt, lưới va chạm từng vật và vá nền. Xong bước này mới đi bộ (Walk) và xuất gói được.",
};

/** Bước hệ thống tạo bộ LOD sau khi scene đã xem được (T-070): scene lớn mở nhanh rồi mịn dần, đủ chất lượng. */
export const VIEW_LOD_STAGE: StageMeta = {
  id: "ST-VIEW-LOD",
  title: "Chuẩn bị xem 3D mượt",
  short: "Chuẩn bị xem",
  description: "Chuẩn bị bản 3D lớn để lần sau mở nhanh và xoay mượt. Vẫn xem được scene trong lúc này.",
};

const EXTRA_STAGES: readonly StageMeta[] = [
  LIDAR_STAGE,
  LIDAR_ODOMETRY_STAGE,
  LIDAR_CALIBRATION_QA_STAGE,
  ANONYMIZATION_REVIEW_STAGE,
  OBJECT_CONFIRM_STAGE,
  SCENE_DECOMPOSE_STAGE,
  VIEW_LOD_STAGE,
];

export function stageMeta(id: StageId): StageMeta | undefined {
  return EXTRA_STAGES.find((stage) => stage.id === id) ?? STUDIO_STAGES.find((stage) => stage.id === id);
}
