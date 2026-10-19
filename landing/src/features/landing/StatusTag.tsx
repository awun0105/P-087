import { STATUS_LABEL, type Status } from "@/features/landing/content";

/** Nhãn trạng thái: luôn có chữ đi kèm màu (UX spec §7.4). */
export function StatusTag({ status, label }: { status: Status; label?: string }) {
  return (
    <span className="lp-status" data-status={status}>
      <span aria-hidden className="lp-status-dot" />
      {label ?? STATUS_LABEL[status]}
    </span>
  );
}
