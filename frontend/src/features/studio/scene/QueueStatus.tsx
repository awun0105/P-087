import type { QueuePositionView } from "@/lib/contracts/studio";

/** "khoảng 12 phút" / "khoảng 1 giờ 5 phút": ước tính nên làm tròn tới phút, không hiện giây. */
export function roughDuration(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `khoảng ${minutes} phút`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `khoảng ${hours} giờ ${rest} phút` : `khoảng ${hours} giờ`;
}

/**
 * Vị trí của job trong hàng đợi và thời gian chờ ước tính. Thứ tự là thứ tự worker thật sự nhận job (xoay vòng theo
 * người yêu cầu). Thời gian chỉ hiện khi backend có số đo của các lượt chạy trước; không có thì nói rõ là chưa ước
 * tính được, không điền số.
 */
export function QueueStatus({ queue }: { queue: QueuePositionView }) {
  const ahead = queue.position - 1;
  return (
    <div className="rounded-lg bg-paper-sunken p-3" data-testid="queue-status">
      <p className="font-medium text-ink">
        {ahead === 0 ? "Scene của bạn là việc kế tiếp." : `Trước bạn còn ${ahead} việc đang chờ.`}
        {queue.running > 0 ? ` ${queue.running} việc đang chạy trên ${queue.workers} máy xử lý.` : ""}
      </p>
      <p className="mt-0.5">
        {queue.estimated_wait_seconds === null
          ? "Chưa ước tính được thời gian chờ."
          : queue.estimated_wait_seconds < 30
            ? "Dự kiến bắt đầu ngay khi máy xử lý rảnh."
            : `Dự kiến chờ ${roughDuration(queue.estimated_wait_seconds)}.`}
      </p>
      {queue.waiting > 1 && <p className="mt-1 text-xs text-ink-subtle">Mỗi người một lượt, rồi mới tới việc thứ hai của từng người.</p>}
    </div>
  );
}
