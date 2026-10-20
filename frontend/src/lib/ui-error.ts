import { ApiError } from "@/lib/api/client";

const FALLBACK = "Không thực hiện được thao tác. Hãy thử lại.";
/** Dấu hiệu của chi tiết kỹ thuật không được đưa vào giao diện: trace, đường dẫn máy chủ, URI/URL, checksum, JSON, HTML. */
const TECHNICAL = /Traceback|chrome-extension:|\/home\/|\/tmp\/|\/usr\/|[a-z][a-z0-9+.-]*:\/\/|sha256:|[\r\n]|^[\[{]|<[a-z!/]/i;
/** Câu mặc định của framework/proxy (không phải thông điệp backend viết cho người dùng). */
const FRAMEWORK_DEFAULTS = new Set([
  "not found", "method not allowed", "not authenticated", "unauthorized", "forbidden", "bad request", "conflict",
  "unprocessable entity", "unprocessable content", "too many requests", "request entity too large",
  "internal server error", "bad gateway", "service unavailable", "gateway timeout",
]);

function safeText(message: string): string | null {
  return !message || TECHNICAL.test(message) || message.length > 400 ? null : message;
}

/**
 * `detail` mà backend viết cho người dùng: một câu nêu lý do (và thường cả cách sửa), vd "A–B quá ngắn so với
 * C–D…; chọn vật dài hơn làm A–B". Chuỗi một từ, câu mặc định của framework hay chi tiết kỹ thuật thì coi là
 * thông điệp thô của tầng truyền tải và không hiện.
 */
function userFacingDetail(error: ApiError): string | null {
  const detail = safeText(error.detail.trim());
  if (!detail || !/\s/.test(detail) || FRAMEWORK_DEFAULTS.has(detail.toLowerCase()) || /^HTTP \d{3}$/.test(detail)) return null;
  return detail;
}

/**
 * Thông điệp vận hành, không đưa raw JSON/trace/path máy chủ vào giao diện.
 *
 * Backend dùng 403/409/429 (và 400/422) cho quy tắc nghiệp vụ và viết lý do cho người dùng trong `detail`; lý do
 * đó được ưu tiên khi an toàn để hiện, vì câu chung theo mã HTTP không nói được phải sửa gì (409 không chỉ là
 * "dữ liệu đã đổi": còn là điểm đo chưa hợp lệ, scene chưa ở đúng bước, đang có yêu cầu khác…). Riêng 401 và 404
 * giữ hướng phục hồi chung (đăng nhập lại / quay về Scenes); thao tác tài khoản
 * dùng `authErrorMessage` vì ở đó 401 là bị từ chối có lý do, không phải hết phiên.
 */
export function errorMessage(cause: unknown, fallback = FALLBACK): string {
  if (cause instanceof ApiError) {
    if (cause.status === 0) return "Không kết nối được máy chủ. Kiểm tra kết nối rồi thử lại.";
    if (cause.status >= 500) return "Máy chủ chưa xử lý được yêu cầu. Hãy thử lại.";
    if (cause.status === 401) return "Phiên đăng nhập đã hết hạn. Đăng nhập để tiếp tục.";
    if (cause.status === 404) return "Không tìm thấy dữ liệu. Tải lại trang hoặc quay về Scenes.";
    const detail = userFacingDetail(cause);
    if (detail) return detail;
    if (cause.status === 403) return "Tài khoản chưa có quyền thực hiện thao tác này.";
    if (cause.status === 409) return "Dữ liệu đã thay đổi hoặc thao tác đang xung đột. Tải lại dữ liệu trước khi thử lại.";
    if (cause.status === 429) return "Đã đạt hạn mức xử lý. Kiểm tra hạn mức tài khoản hoặc thử lại sau.";
    if (cause.status === 422 && /^[\[{]/.test(cause.detail.trim())) return "Dữ liệu chưa hợp lệ. Kiểm tra các trường và điều kiện của thao tác.";
    // Mã khác (400, 405, 413…) mà không có câu dành cho người dùng: không hiện chuỗi thô của framework/proxy.
    return fallback;
  }
  const message = cause instanceof Error ? cause.message : typeof cause === "string" ? cause : "";
  return safeText(message) ?? fallback;
}

/**
 * Lỗi của các thao tác tài khoản (đăng nhập, đăng ký bằng mã mời, mời/đổi quyền thành viên). Backend trả 401 cho
 * mọi từ chối ở nhóm này — sai email/mật khẩu, mã mời không dùng được, tự hạ quyền — nên ở đây 401 không có
 * nghĩa "phiên hết hạn": hiện đúng lý do backend trả; các lỗi khác đi qua `errorMessage`.
 */
export function authErrorMessage(cause: unknown, fallback = FALLBACK): string {
  if (cause instanceof ApiError && cause.status === 401) return userFacingDetail(cause) ?? fallback;
  return errorMessage(cause, fallback);
}
