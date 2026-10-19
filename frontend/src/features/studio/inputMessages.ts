/**
 * Thông điệp người dùng cho kết quả nhận diện input.
 *
 * Backend trả mã ổn định (`SCAN_SEQUENCE_ORDER_REQUIRED`…) kèm mô tả tiếng Anh cho nhật ký; giao diện chỉ hiện
 * câu tiếng Việt ở đây. Mã chưa có trong danh mục rơi về `description` của máy chủ để không mất thông tin, và
 * `tests/test_reconstruction/test_input_message_catalog.py` làm hỏng build khi backend thêm mã mà chưa dịch.
 */
import type {
  InputResolutionCandidate,
  MissingInputFact,
  ResolutionDiagnostic,
} from "@/lib/contracts/inputAssembly";

export const INPUT_MESSAGES: Record<string, string> = {
  // Thiếu hoặc cần bổ sung
  RGB_VIDEO_REQUIRED: "Thiếu video RGB.",
  VIDEO_SELECTION_REQUIRED: "Có nhiều video. Chọn đúng một video để dựng.",
  GAUSSIAN_SCENE_REQUIRED: "Thiếu file scene 3DGS (.ply hoặc .sog).",
  GAUSSIAN_MASTER_SELECTION_REQUIRED: "Có nhiều file 3DGS. Chọn đúng một file chính.",
  WORKFLOW_INTENT_REQUIRED: "Bộ file có cả video và scene 3DGS. Chọn dựng từ video hay chỉ xem 3DGS.",
  CLOUD_STATE_REQUIRED: "Cho biết đám mây LiDAR là map đã ghép, một lần quét tĩnh hay chuỗi scan thô.",
  MAP_FILE_SELECTION_REQUIRED: "Có nhiều đám mây. Chọn đúng file dùng làm map.",
  CLOUD_CHOICES_TRUNCATED: "Có quá nhiều đám mây nên chỉ hiện một phần. Hãy chọn đúng file dùng làm map.",
  SAME_SCENE_REQUIRED: "Xác nhận video và LiDAR quay cùng một cảnh.",
  COORDINATE_UNIT_REQUIRED: "Khai đơn vị toạ độ của LiDAR (m, cm hoặc mm).",
  LIDAR_FRAME_REQUIRED: "Khai tên hệ toạ độ (frame) của LiDAR.",
  CAMERA_FRAME_REQUIRED: "Khai tên frame của camera trong file calibration ROS để kiểm đúng hai đầu của file.",
  SENSOR_TRAJECTORY_CONVENTION_REQUIRED: "Xác nhận quỹ đạo là pose của cảm biến LiDAR (world_from_sensor).",
  SCAN_SEQUENCE_NEEDS_MULTIPLE_FILES: "Chuỗi scan cần ít nhất hai file.",
  SCAN_SEQUENCE_ORDER_REQUIRED: "Kiểm tra và xác nhận thứ tự scan theo thời gian.",
  SCAN_FORMAT_PCD_REQUIRED: "Chuỗi scan có quỹ đạo sẵn cần ở dạng .pcd, mỗi scan một file.",
  SCAN_POSE_PAIRING_REQUIRED: "Số pose của quỹ đạo phải bằng số scan.",
  CAMERA_LIDAR_CALIBRATION_REQUIRED: "Thiếu file calibration camera ↔ LiDAR.",
  CALIBRATION_SELECTION_REQUIRED: "Có nhiều file calibration. Chọn đúng một file.",
  RGB_FRAME_TIMES_REQUIRED: "Thiếu file thời điểm từng frame của video.",
  FRAME_TIMES_SELECTION_REQUIRED: "Có nhiều file thời điểm frame. Chọn đúng một file.",
  RGB_FRAME_TIMES_COUNT_MISMATCH: "File thời điểm frame cần đúng một dòng cho mỗi pose của quỹ đạo.",
  RGB_TIMESTAMP_UNIT_REQUIRED: "Khai đơn vị thời gian của file thời điểm frame.",
  LIDAR_SCAN_TIMESTAMPS_REQUIRED: "Cần một file thời điểm scan, mỗi scan một dòng.",
  LIDAR_SCAN_TIMESTAMPS_COUNT_MISMATCH: "Số dòng thời điểm scan phải bằng số scan.",
  LIDAR_TIMESTAMP_UNIT_REQUIRED: "Khai đơn vị thời gian của thời điểm scan LiDAR.",
  CLOCK_RELATION_REQUIRED: "Cho biết đồng hồ camera và LiDAR cùng nguồn, lệch đã biết hay không rõ.",
  CLOCK_OFFSET_REQUIRED: "Nhập độ lệch đồng hồ giữa camera và LiDAR (giây).",
  VERIFIED_RGB_FRAME_MAP_REQUIRED: "Cần video đã chuẩn bị ở trình duyệt và được máy chủ xác minh khung hình.",
  ROUTE_SELECTION_REQUIRED: "Có nhiều cách xử lý ngang nhau. Chọn một cách.",

  // Mâu thuẫn hoặc dữ liệu sai
  SCENE_MISMATCH: "Bạn khai video và LiDAR là hai cảnh khác nhau nên không dùng chung được.",
  CONFLICTING_CLOUD_BINDINGS: "Các file LiDAR đang được gán theo cách mâu thuẫn nhau.",
  CONFLICTING_CLOUD_STATE: "Loại đám mây đã khai không khớp với vai trò đã gán cho file.",
  ROLE_FORMAT_MISMATCH: "Một file được gán vai trò không phù hợp với nội dung của nó.",
  TIMESTAMP_FILE_ROLE_CONFLICT: "Một file thời điểm không thể vừa của camera vừa của LiDAR.",
  TRAJECTORY_CONVENTION_CONFLICT: "Quy ước quỹ đạo đã khai mâu thuẫn với vai trò của file.",
  CAMERA_TRAJECTORY_NOT_SENSOR_TRAJECTORY: "Quỹ đạo của camera không thay được quỹ đạo của cảm biến LiDAR.",
  DUPLICATE_PROBE: "Kết quả nhận diện bị trùng. Tải lại file.",
  PROBE_FORMAT_MISMATCH: "File đã thay đổi sau khi tải lên. Tải lại file.",
  PROBE_INVENTORY_MISMATCH: "Danh sách file đã thay đổi sau khi tải lên. Tải lại file.",
  PROBE_MEMBER_CHECKSUM_MISMATCH: "Một file trong ZIP đã thay đổi sau khi tải lên. Tải lại file.",
  PROBE_SOURCE_CHECKSUM_MISMATCH: "File đã thay đổi sau khi tải lên. Tải lại file.",
  UNSUPPORTED_INPUT_CONTENT: "Không tìm thấy nội dung nào hệ thống dùng được trong các file này.",
  UNSUPPORTED_RUNTIME: "Máy này chưa có bộ xử lý phù hợp cho các cách xử lý này.",
  ODOMETRY_RUNTIME_UNAVAILABLE: "Chưa có bộ ước lượng quỹ đạo LiDAR khả dụng trên máy này.",
  ODOMETRY_RUNTIME_UNQUALIFIED: "Bộ ước lượng quỹ đạo LiDAR chưa được kiểm định.",

  // Thông tin về lựa chọn của hệ thống
  ROUTE_AUTO_SELECTED: "Hệ thống đã tự chọn cách xử lý phù hợp nhất với dữ liệu bạn đưa vào.",
  ALTERNATIVE_ROUTE_NOT_USED: "Còn một cách xử lý khác cũng chạy được; hệ thống ưu tiên cách có ràng buộc hình học mạnh hơn.",
  HIGHER_ROUTE_NEEDS_MORE_FACTS: "Bổ sung thêm thông tin còn thiếu sẽ cho phép dùng cách xử lý chính xác hơn.",
  HIGHER_ROUTE_UNAVAILABLE: "Cách xử lý tốt hơn chưa chạy được trên máy này nên đang dùng cách đơn giản hơn.",
  UNUSED_INPUTS_EXCLUDED: "Một số file không có chỗ dùng trong cách xử lý này nên được bỏ qua.",
  TIMESTAMP_ROLE_INFERRED: "Vai trò file thời điểm được suy theo số dòng khớp số pose hoặc số scan.",

  // Chẩn đoán lúc đọc file
  ambiguous_calibration_direction: "File calibration khai cả hai chiều. Chỉ giữ một chiều.",
  ambiguous_text_roles: "Một file văn bản vừa là calibration vừa là quỹ đạo. Tách thành hai file.",
  empty_archive: "File ZIP trống, không có file nào bên trong.",
  invalid_calibration_json: "File calibration JSON có số liệu không hợp lệ (ma trận, quaternion hoặc kích thước).",
  invalid_calibration_yaml: "File calibration YAML có cấu trúc hoặc số liệu không hợp lệ.",
  invalid_pcd: "File .pcd không đọc được.",
  invalid_ply: "File .ply không đọc được.",
  invalid_sog: "File .sog không hợp lệ.",
  invalid_timestamp_rows: "File thời điểm cần mỗi dòng một số và tăng dần.",
  invalid_tum_trajectory: "File quỹ đạo cần đúng 8 số mỗi dòng và thời gian tăng dần.",
  kalibr_camera_imu_only: "File Kalibr chỉ có camera ↔ IMU, chưa dùng được làm calibration camera ↔ LiDAR.",
  source_size_mismatch: "File tải lên không khớp kích thước đã ghi. Tải lại file.",
  text_probe_too_large: "File văn bản quá lớn (trên 16 MiB).",
  unreadable_upload: "Không đọc được file. Tải lại file.",
};

/** Câu tiếng Việt cho một mã; mã lạ rơi về mô tả của máy chủ. */
export function describeInputCode(code: string, fallback: string): string {
  return INPUT_MESSAGES[code] ?? fallback;
}

export function describeFact(fact: MissingInputFact): string {
  return describeInputCode(fact.code, fact.description);
}

export function describeDiagnostic(item: ResolutionDiagnostic): string {
  return describeInputCode(item.code, item.description);
}

const ROUTE_NAMES: Record<string, string> = {
  R1: "Chỉ video",
  R2: "Video + map LiDAR đã ghép",
  R3: "Video + một lần quét LiDAR",
  R4: "Video + chuỗi scan + quỹ đạo có sẵn",
  R5: "Video + chuỗi scan (tự ước lượng quỹ đạo)",
  R6: "Video + LiDAR + calibration (dẫn hướng bằng cảm biến)",
};

/** Tên cách xử lý cho người dùng; mã nhóm R1–R6 không hiện ra ngoài. */
export function routeName(candidate: InputResolutionCandidate): string {
  if (candidate.candidate_kind === "gaussian_view_import") {
    return candidate.source_format === "gaussian_sog" ? "Xem scene 3DGS (.sog)" : "Xem scene 3DGS (.ply)";
  }
  return ROUTE_NAMES[candidate.recipe_group] ?? "Cách xử lý khác";
}
