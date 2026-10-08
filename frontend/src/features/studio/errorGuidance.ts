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
        cause: "Driver GPU ngừng phản hồi khi dựng 3DGS.",
        fix: "Thử lại. Nếu lặp lại, báo quản trị viên kiểm tra driver GPU.",
      };

    case "VISUAL_HANG_TIMEOUT":
      return {
        cause: "Bước dựng 3DGS không có tiến triển trong thời gian dài.",
        fix: "Thử lại. Job tiếp tục từ checkpoint đã lưu.",
      };

    case "VISUAL_TIMEOUT":
      return {
        cause: "Bước dựng 3DGS chạy quá thời gian cho phép.",
        fix: 'Giảm "Số bước huấn luyện 3DGS" hoặc thử lại.',
      };

    default:
      return null;
  }
}
