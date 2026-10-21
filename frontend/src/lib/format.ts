/** Định dạng số liệu hiển thị (dung lượng, thời lượng) — thuần, không phụ thuộc UI. */

/** Định dạng dung lượng file theo đơn vị nhị phân, 1 chữ số thập phân. */
export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** "3 phút 12 giây" — thời lượng đo được, không làm tròn thành ước lượng. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  if (hours > 0) return `${hours} giờ ${minutes} phút`;
  if (minutes > 0) return `${minutes} phút ${rest} giây`;
  return `${rest} giây`;
}

/** Thời gian chờ người dùng: "12 phút", "3 giờ 5 phút", "3 ngày 15 giờ" (không để "5248 phút"). */
export function formatWait(seconds: number): string {
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} phút`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} giờ ${minutes % 60} phút`;
  return `${Math.floor(hours / 24)} ngày ${hours % 24} giờ`;
}

/** Mốc cập nhật: chỉ giờ khi là hôm nay, kèm ngày khi đã cũ (tránh tưởng một mốc từ mấy hôm trước là của hôm nay). */
export function formatUpdatedAt(iso: string, now: number = Date.now()): string {
  const at = new Date(iso);
  const sameDay = at.toDateString() === new Date(now).toDateString();
  return sameDay ? at.toLocaleTimeString("vi-VN") : `${at.toLocaleTimeString("vi-VN")} ${at.toLocaleDateString("vi-VN")}`;
}
