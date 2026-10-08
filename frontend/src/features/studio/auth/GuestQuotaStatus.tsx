import type { GuestQuotaSummary } from "@/lib/api/auth";

export function GuestQuotaStatus({
  quota,
  className = "",
}: {
  quota?: GuestQuotaSummary | null;
  className?: string;
}) {
  const resetAt = quota
    ? new Intl.DateTimeFormat("vi-VN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: quota.timezone,
      }).format(new Date(quota.resets_at_utc))
    : null;

  return (
    <div aria-live="polite" className={`rounded-md border border-line bg-paper-raised px-3 py-2 text-xs text-ink ${className}`}>
      {quota ? (
        <>
          <p className="font-medium">Guest còn {quota.remaining}/{quota.limit} lượt hôm nay.</p>
          <p className="mt-0.5 text-ink-muted">
            Đã dùng {quota.used}/{quota.limit}; đặt lại lúc {resetAt} (giờ Việt Nam).
          </p>
        </>
      ) : (
        <>
          <p className="font-medium">Chưa tải được số lượt Guest còn lại.</p>
          <p className="mt-0.5 text-ink-muted">Máy chủ sẽ kiểm tra hạn mức khi nhận yêu cầu.</p>
        </>
      )}
    </div>
  );
}
