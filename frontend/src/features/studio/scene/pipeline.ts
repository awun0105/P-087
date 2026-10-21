import type { TimelineStageView } from "@/features/studio/PipelineTimeline";
import { stageMeta, type TimelineStageMeta } from "@/features/studio/stages";
import type { NextActionKind, PipelineView } from "@/lib/contracts/pipeline";
import { formatWait } from "@/lib/format";
import { geometryPhaseLabel } from "@/lib/scene/geometry-state";

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

/** Dữ liệu dòng tiến trình vẽ thẳng từ bước của backend (T-061): không hàng giả, không ghi đè trạng thái. */
export function timelineFromSteps(view: PipelineView, now: number): { stages: TimelineStageView[]; stageList: TimelineStageMeta[] } {
  const stageList: TimelineStageMeta[] = [];
  const stages: TimelineStageView[] = [];
  for (const step of view.steps) {
    const meta = stageMeta(step.step_id);
    stageList.push(meta ?? { id: step.step_id, title: step.step_id, short: step.step_id, description: "" });
    const started = step.started_at ? Date.parse(step.started_at) : null;
    const ended = step.completed_at ? Date.parse(step.completed_at) : step.state === "running" ? now : null;
    const seconds = step.actor === "system" && started !== null && ended !== null && ended >= started ? Math.round((ended - started) / 1000) : null;
    const notes: string[] = [];
    if (step.state === "queued") notes.push("Đang chờ máy xử lý");
    if (step.actor === "user" && started !== null) {
      const waited = formatWait(((step.completed_at ? Date.parse(step.completed_at) : now) - started) / 1000);
      if (step.state === "waiting") notes.push(`Chờ bạn ${waited}`);
      else if (step.state === "succeeded" && step.completed_at) notes.push(`Bạn xử lý trong ${waited}`);
    }
    const phase = geometryPhaseLabel(step.phase);
    if (phase) notes.push(phase);
    if (step.note) notes.push(step.note);
    stages.push({
      stage_id: step.step_id,
      state: step.state === "queued" || step.state === "skipped" ? "pending" : step.state,
      seconds,
      fraction: null,
      error: step.error,
      note: notes.join(" · ") || null,
    });
  }
  return { stages, stageList };
}
