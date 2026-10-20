/**
 * Mô hình tiến trình hợp nhất `GET /api/v1/jobs/{id}/pipeline` (T-059). Khớp `PipelineViewResponse` ở backend.
 */
import type { GpuCapacity } from "@/lib/api/gpu";
import type { ObjectifyState } from "@/lib/api/studio";
import type { ExecutionError, StageId } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";

export type NextActionKind =
  | "wait_system"
  | "review_anonymization"
  | "confirm_metric"
  | "retry_job"
  | "job_failed"
  | "job_cancelled"
  | "retry_geometry"
  | "review_objects"
  | "choose_object_method"
  | "confirm_objects"
  | "scene_ready"
  | "released"
  | "await_review"
  | "review_package"
  | "fix_preflight"
  | "create_package";

export interface NextAction {
  kind: NextActionKind;
  step_id: StageId | null;
  owner: "system" | "user";
  pending_count: number | null;
}

export type StepActor = "system" | "user";
/** `waiting` chỉ khi chờ người; chờ máy là `queued`. */
export type StepState = "pending" | "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled" | "skipped";
export type TimingSource = "recorded" | "inferred" | "none";

export interface PipelineStep {
  step_id: StageId;
  actor: StepActor;
  state: StepState;
  started_at: string | null;
  completed_at: string | null;
  timing_source: TimingSource;
  phase: string | null;
  error: ExecutionError | null;
  note: string | null;
}

export interface PipelineWait {
  kind: "user" | "queue" | "resources" | "runtime" | "scene_operation";
  step_id: StageId | null;
  since: string | null;
}

export interface PipelineView {
  job_id: string;
  scene_revision: string | null;
  usable: boolean;
  steps: PipelineStep[];
  current_step: StageId | null;
  wait: PipelineWait | null;
  next_action: NextAction;
  version: string;
  progress: JobProgress;
  objectify: ObjectifyState | null;
  gpu: GpuCapacity | null;
}
