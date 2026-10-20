import type { NextActionKind, PipelineView } from "@/lib/contracts/pipeline";

/** Việc đã xong hoặc chỉ còn việc không gấp: hỏi lại thưa (vẫn bắt được thay đổi từ nơi khác). */
const SETTLED: ReadonlySet<NextActionKind> = new Set([
  "released",
  "job_failed",
  "job_cancelled",
  "scene_ready",
  "create_package",
  "review_package",
  "await_review",
  "fix_preflight",
  "confirm_objects",
]);

/**
 * Nhịp hỏi `/pipeline` (T-060): 3 s khi máy đang làm, 15 s khi chờ người (xác nhận ở tab khác vẫn hiện trong ≤ 15 s),
 * 60 s khi không còn gì gấp. Không bao giờ dừng hẳn.
 */
export function pipelinePollInterval(view: PipelineView | null): number {
  if (view === null) return 3000;
  const busy = view.next_action.owner === "system" || view.steps.some((step) => step.state === "running" || step.state === "queued");
  if (busy) return 3000;
  return SETTLED.has(view.next_action.kind) ? 60000 : 15000;
}
