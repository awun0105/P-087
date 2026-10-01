import { ApiError } from "@/lib/api/client";

/** Thông điệp vận hành, không đưa raw JSON/trace/path máy chủ vào giao diện. */
export function errorMessage(cause: unknown, fallback = "Không thực hiện được thao tác. Hãy thử lại."): string {
  if (cause instanceof ApiError) {
    if (cause.status === 0) return "Không kết nối được máy chủ. Kiểm tra kết nối rồi thử lại.";
    if (cause.status === 401) return "Phiên đăng nhập đã hết hạn. Đăng nhập để tiếp tục.";
    if (cause.status === 403) return "Tài khoản chưa có quyền thực hiện thao tác này.";
    if (cause.status === 404) return "Không tìm thấy dữ liệu. Tải lại trang hoặc quay về Scenes.";
    if (cause.status === 409) return "Dữ liệu đã thay đổi hoặc thao tác đang xung đột. Tải lại dữ liệu trước khi thử lại.";
    if (cause.status === 429) return "Đã đạt hạn mức xử lý. Kiểm tra hạn mức tài khoản hoặc thử lại sau.";
    if (cause.status >= 500) return "Máy chủ chưa xử lý được yêu cầu. Hãy thử lại.";
    if (cause.status === 422 && /^[\[{]/.test(cause.detail.trim())) return "Dữ liệu chưa hợp lệ. Kiểm tra các trường và điều kiện của thao tác.";
  }
  const message = cause instanceof Error ? cause.message : typeof cause === "string" ? cause : "";
  if (!message || /Traceback|chrome-extension:|\/home\/|\/tmp\/|\/usr\/|https?:\/\/|[\r\n]|^[\[{]/.test(message) || message.length > 400) return fallback;
  return message;
}
