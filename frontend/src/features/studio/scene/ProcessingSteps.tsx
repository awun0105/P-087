import type { JobStepView } from "@/lib/contracts/studio";
import { formatDuration } from "@/lib/format";
import { stageSeconds } from "@/features/studio/scene/state";

/** Tên bước xếp lịch (T-073) cho người dùng; khác tên stage của timeline vì một bước có thể gồm nhiều stage. */
export const STEP_LABELS: Record<JobStepView["step_id"], string> = {
  prepare: "Chuẩn bị video",
  anonymization_review: "Duyệt bản đã che",
  pose_visual: "Dựng camera và 3D",
  metric_confirm: "Xác nhận tỉ lệ",
  canonical_geometry: "Dựng hình học",
  scene_extract: "Tách vật thể",
  view_lod: "Tạo bản xem nhẹ",
};

const KIND_LABELS: Record<JobStepView["kind"], string> = { cpu: "CPU", gpu: "GPU", user: "Bạn" };

/** Câu trạng thái của một bước; bước sẵn sàng nói rõ đang chờ máy có GPU hay CPU trống. */
export function stepStatusText(step: JobStepView): string {
  switch (step.state) {
    case "ready":
      return step.waiting_on === "gpu" ? "Đang chờ GPU trống" : step.waiting_on === "cpu" ? "Đang chờ CPU trống" : "Đang chờ máy xử lý";
    case "claimed":
      return "Máy xử lý vừa nhận";
    case "running":
      return "Đang chạy";
    case "waiting_user":
      return "Chờ bạn";
    case "done":
      return "Xong";
    case "failed":
      return "Lỗi";
    case "skipped":
      return "Bỏ qua";
    default:
      return "Chưa tới";
  }
}

/**
 * Các bước xếp lịch của job: bước CPU và bước GPU của các job khác nhau chạy chồng lên nhau, nên khi chờ, dòng này
 * nói đúng bước nào đang chờ loại máy nào. Thời gian chỉ hiện khi backend ghi được mốc bắt đầu.
 */
export function ProcessingSteps({ steps, now }: { steps: JobStepView[]; now: number }) {
  if (steps.length === 0) return null;
  return (
    <ol className="mb-5 grid gap-1.5 text-sm sm:grid-cols-2" aria-label="Các bước xử lý" data-testid="processing-steps">
      {steps.map((step) => {
        const seconds = step.state === "running" || step.state === "done" || step.state === "failed"
          ? stageSeconds(step.started_at, step.finished_at, step.state === "running" ? now : null)
          : null;
        const active = step.state === "running" || step.state === "ready" || step.state === "claimed" || step.state === "waiting_user";
        return (
          <li key={step.step_id} className={"flex items-center justify-between gap-3 rounded-lg px-3 py-1.5 " + (active ? "bg-paper-sunken text-ink" : "text-ink-muted")}>
            <span className="flex min-w-0 items-center gap-2">
              <span className="shrink-0 rounded border border-line px-1.5 text-[11px] font-medium uppercase tracking-wide">{KIND_LABELS[step.kind]}</span>
              <span className="truncate">{STEP_LABELS[step.step_id]}</span>
            </span>
            <span className="shrink-0 text-xs">
              {stepStatusText(step)}
              {seconds !== null && seconds >= 1 ? ` · ${formatDuration(seconds)}` : ""}
              {step.attempt > 1 && (step.state === "running" || step.state === "ready") ? ` · lần ${step.attempt}` : ""}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
