import { STATUS_LABEL, type Status } from "@/features/landing/content";

/** Nhãn trạng thái: luôn có chữ đi kèm màu (UX spec §7.4). */
export function StatusTag({ status }: { status: Status }) {
  return (
    <span className="lp-status" data-status={status}>
      <span aria-hidden className="lp-status-dot" />
      {STATUS_LABEL[status]}
    </span>
  );
}
