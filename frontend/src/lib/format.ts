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
