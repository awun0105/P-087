import { GAUSSIAN_EDIT_ENABLED } from "@/features/studio/scene/state";

export type Source = "video" | "gaussian" | "sample";

/**
 * Mỗi cách bắt đầu là một trang riêng dưới `/new`. `/new` và `/new/import-video` cùng là khung tải
 * input chung (`UnifiedInputFlow`): mọi scene dựng mới đi qua đó, kể cả khi có thêm LiDAR/metadata.
 */
export const SOURCE_ROUTES: Record<Source, string> = {
  video: "/new/import-video",
  gaussian: "/new/import-scene",
  sample: "/new/try-demo",
};

/** Tên và mô tả duy nhất của ba cách bắt đầu: trang chọn, tiêu đề từng trang và breadcrumb đều đọc từ đây. */
export const SOURCE_TITLES: Record<Source, { title: string; description: string }> = {
  video: { title: "Dựng từ video", description: "Tải video MP4/MOV, khai báo dữ liệu rồi bắt đầu dựng scene 3D." },
  gaussian: { title: "Mở 3DGS có sẵn", description: (GAUSSIAN_EDIT_ENABLED ? "Tải file PLY/SOG/ZIP đã dựng để xem, chỉnh Gaussian và xuất file." : "Tải file PLY/SOG/ZIP đã dựng để xem.") + " Không có tỉ lệ mét, collision hay duyệt." },
  sample: { title: "Thử mẫu", description: "Xem tiến trình và kết quả đã xử lý sẵn; không tạo scene mới." },
};
