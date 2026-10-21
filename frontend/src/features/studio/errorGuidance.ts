import type { ExecutionError } from "@/lib/contracts/api";

export interface ErrorGuidance {
  cause: string;
  fix?: string;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Tra cứu nguyên nhân và hướng khắc phục thân thiện với người dùng theo error_code.
 * Trả null nếu mã lỗi không có hướng dẫn chuyên biệt.
 */
export function guidanceFor(error: ExecutionError | null | undefined): ErrorGuidance | null {
  if (!error || !error.error_code) {
    return null;
  }

  const details = error.details ?? undefined;

  switch (error.error_code) {
    case "COLMAP_NO_MODEL": {
      const diagnosticsValue = details?.diagnostics;
      const diagnostics =
        typeof diagnosticsValue === "object" && diagnosticsValue !== null && !Array.isArray(diagnosticsValue)
          ? (diagnosticsValue as Record<string, unknown>)
          : undefined;
      const noInitialPair = finiteNumber(diagnostics?.no_initial_pair) ?? 0;
      const fix =
        noInitialPair > 0
          ? "Các khung hình liên tiếp không có đủ điểm chung. Quay chậm hơn, giữ vật thể trong khung và tránh bề mặt trơn một màu."
          : "Cảnh bị tách thành nhiều đoạn rời. Quay một vòng liền mạch, không cắt ngang.";
      return {
        cause: "Không dựng được vị trí camera từ video này.",
        fix,
      };
    }

    case "COLMAP_REGISTRATION_LOW": {
      const registered = finiteNumber(details?.registered_frames);
      const input = finiteNumber(details?.input_frames);
      const minRatio = finiteNumber(details?.min_registered_ratio);
      const threshold = minRatio === null ? "ngưỡng tối thiểu" : `ngưỡng ${new Intl.NumberFormat("vi-VN", { style: "percent", maximumFractionDigits: 1 }).format(minRatio)}`;
      const cause = registered !== null && input !== null && input > 0
        ? `Chỉ dựng được vị trí cho ${registered}/${input} ảnh, dưới ${threshold}.`
        : `Chỉ dựng được vị trí camera cho một phần số ảnh, dưới ${threshold}.`;
      return {
        cause,
        fix: "Quay chậm hơn và để các khung hình liên tiếp chồng lấn nhiều hơn.",
      };
    }

    case "FRAME_ANONYMIZATION_FAILED":
      return {
        cause: "Chưa che xong khuôn mặt và biển số nên chưa dựng 3D.",
        fix: "Thử lại. Nếu vẫn lỗi, báo quản trị viên.",
      };

    case "FRAME_ANONYMIZER_UNAVAILABLE":
      return {
        cause: "Máy xử lý chưa cài công cụ che khuôn mặt và biển số.",
        fix: "Báo quản trị viên để cài đặt.",
      };

    case "COLMAP_OUT_OF_MEMORY":
      return {
        cause: "Máy xử lý hết RAM khi dựng vị trí camera.",
        fix: 'Giảm "Số khung hình tối đa" hoặc "Số điểm đặc trưng mỗi ảnh" rồi chạy lại.',
      };

    case "COLMAP_TIMEOUT":
      return {
        cause: "Bước dựng vị trí camera chạy quá thời gian cho phép.",
        fix: 'Giảm "Số khung hình tối đa" hoặc thử lại khi máy xử lý rảnh.',
      };

    case "VISUAL_OUT_OF_MEMORY":
      return {
        cause: "GPU hết bộ nhớ khi dựng 3DGS.",
        fix: 'Giảm "Số Gaussian tối đa" hoặc "Độ phân giải huấn luyện" rồi chạy lại.',
      };

    case "VISUAL_GPU_DEADLOCK":
      return {
        cause: "GPU ngừng phản hồi khi dựng 3DGS.",
        fix: "Thử lại. Nếu vẫn lỗi, báo quản trị viên.",
      };

    case "VISUAL_HANG_TIMEOUT":
      return {
        cause: "Bước dựng 3DGS không có tiến triển trong thời gian dài.",
        fix: "Thử lại. Lần chạy sau tiếp tục từ chỗ đã lưu.",
      };

    case "VISUAL_TIMEOUT":
      return {
        cause: "Bước dựng 3DGS chạy quá thời gian cho phép.",
        fix: 'Giảm "Số bước huấn luyện 3DGS" hoặc thử lại.',
      };

    case "PROCESS_STALLED":
      return {
        cause: "Một bước bị treo quá lâu nên đã dừng.",
        fix: "Thử lại. Nếu vẫn lỗi, báo quản trị viên.",
      };

    case "LIDAR_ODOMETRY_STALLED":
      return {
        cause: "Bước ước lượng quỹ đạo LiDAR bị treo quá lâu nên đã dừng.",
        fix: "Thử lại. Nếu vẫn lỗi, báo quản trị viên.",
      };

    case "OBJECTIFY_AWAITING_CHOICE":
      return {
        cause: "Tách cảnh thành từng vật chưa thành công sau các lần thử.",
        fix: "Chạy lại tách theo vật, hoặc dùng hộp ứng viên để tiếp tục với các vật ước lượng bằng hộp.",
      };

    case "OBJECT_GEOMETRY_BUILD_FAILED":
      return {
        cause: "Chưa tạo xong mesh cho các vật. Scene đang duyệt vẫn được giữ.",
        fix: "Sửa vùng vật trong Studio nếu cần, rồi thử lại Tạo mesh.",
      };

    case "RESOURCE_WAIT_EXCEEDED":
      return {
        cause: "Chờ máy xử lý quá lâu nên đã dừng.",
        fix: "Báo quản trị viên kiểm tra máy xử lý, rồi bấm Thử lại.",
      };

    case "INTERRUPTED_SHUTDOWN":
      return {
        cause: "Máy xử lý bị tắt giữa chừng.",
        fix: "Bấm Thử lại. Các bước đã xong được giữ.",
      };

    case "EXPECTED_DURATION_EXCEEDED":
      return {
        cause: "Lượt chạy lâu bất thường nên đã dừng.",
        fix: "Thử lại khi máy rảnh, hoặc giảm \"Số khung hình tối đa\".",
      };

    case "GPU_BUDGET_EXCEEDED":
      return {
        cause: "Scene đã dùng hết số giờ xử lý cho phép.",
        fix: "Cần thêm giờ thì báo quản trị viên.",
      };

    default:
      return null;
  }
}
