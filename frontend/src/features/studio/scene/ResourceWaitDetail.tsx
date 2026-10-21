import type { ResourceWaitReason, ResourceWaitView } from "@/lib/contracts/studio";

const LABEL = { vram: "VRAM GPU", ram: "RAM", disk: "Ổ đĩa" } as const;

/** Mỗi lý do nói rõ việc chờ có tự hết hay cần người dùng làm gì; không tự đổi cấu hình. */
const REASON: Record<ResourceWaitReason, string> = {
  busy: "Việc khác đang dùng phần này. Scene của bạn tự chạy khi việc đó xong.",
  external: "Một chương trình khác trên máy đang chiếm phần này. Nếu chờ lâu, huỷ và tạo lại với cấu hình thấp hơn.",
  exceeds_machine: "Cấu hình vượt sức máy xử lý nên sẽ không chạy. Huỷ và tạo lại với cấu hình thấp hơn.",
  unmeasured: "Máy xử lý chưa đo được phần này nên chưa chạy. Báo quản trị viên.",
  gate_error: "Máy xử lý kiểm tra tài nguyên bị lỗi. Quá 30 phút việc sẽ dừng để bạn thử lại. Báo quản trị viên.",
};

/** Số "cần" của VRAM/RAM lấy từ đâu; đĩa luôn là ước lượng. */
const SOURCE: Record<ResourceWaitView["estimate_scope"], string> = {
  measured: "các lượt chạy trước đã dùng tới",
  upper_bound: "theo số đo của cấu hình nặng hơn, cần tối đa",
  configured_preview: "cần khoảng",
};

function gigabytes(value: number | null | undefined): string {
  return value === null || value === undefined ? "chưa đo được" : `${value.toFixed(1)} GB`;
}

/**
 * Chi tiết lần đo gần nhất của worker khi job chờ tài nguyên: thiếu gì, cần bao nhiêu, đang có bao nhiêu.
 * Số "cần" là số đo của các lượt chạy trước (`measured`), số đo của cấu hình nặng hơn (`upper_bound`) hoặc ước
 * lượng theo cấu hình; UI nói rõ là loại nào.
 */
export function ResourceWaitDetail({ wait }: { wait: ResourceWaitView }) {
  const source = SOURCE[wait.estimate_scope];
  return (
    <div className="rounded-lg bg-paper-sunken p-3">
      <ul className="space-y-2">
        {wait.waiting_on.map((resource) => {
          const reason = wait.reasons?.[resource];
          const capacity = wait.capacity_gb?.[resource];
          // Chưa có số đo: job không được chạy chung GPU, nên con số VRAM không phải là thứ đang thiếu.
          if (resource === "vram" && wait.needs_exclusive_gpu) {
            return (
              <li key={resource}>
                <p className="font-medium text-ink">GPU: đang chờ được chạy một mình</p>
                <p className="mt-0.5">Cấu hình này chạy lần đầu nên cần dùng GPU một mình. Scene tự chạy khi GPU rảnh.</p>
              </li>
            );
          }
          return (
            <li key={resource}>
              <p className="font-medium text-ink">
                {LABEL[resource]}: {resource !== "disk" ? source : "cần khoảng"} {gigabytes(wait.required_gb[resource])}, đang có {gigabytes(wait.available_gb[resource])}
                {capacity !== null && capacity !== undefined ? ` (máy có tổng ${gigabytes(capacity)})` : ""}
              </p>
              {reason && <p className="mt-0.5">{REASON[reason]}</p>}
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-xs text-ink-subtle">Đo lúc {new Date(wait.checked_at).toLocaleTimeString("vi-VN")}.</p>
    </div>
  );
}
