import { describe, expect, it, vi } from "vitest";

import { stepActions, type StepActionHandlers } from "@/features/studio/scene/stepActions";
import { stageMeta } from "@/features/studio/stages";
import type { NextActionKind, PipelineStep, PipelineView } from "@/lib/contracts/pipeline";
import type { StageId } from "@/lib/contracts/api";

function step(step_id: StageId, state: PipelineStep["state"]): PipelineStep {
  return { step_id, actor: "system", state, started_at: null, completed_at: null, timing_source: "none", phase: null, error: null, note: null };
}

function view(kind: NextActionKind, step_id: StageId | null, extra: Partial<PipelineView> = {}): PipelineView {
  return {
    job_id: "job-1", scene_revision: "rev-002", usable: false, current_step: null, wait: null, version: "v",
    next_action: { kind, step_id, owner: "user", pending_count: null }, steps: [],
    progress: { job_id: "job-1", status: "SUCCEEDED", current_stage: "ST-OBJECT-EXTRACT", attempt: 1, started_at: "", updated_at: "", stages: [], preview_ready: true, error: null } as unknown as PipelineView["progress"],
    objectify: { status: "idle", available: true, retryable: true } as PipelineView["objectify"], gpu: null, ...extra,
  };
}

function handlers(): Required<StepActionHandlers> {
  return {
    confirmMetric: vi.fn(), openStudio: vi.fn(), showAnonymization: vi.fn(), retryJob: vi.fn(),
    retryGeometry: vi.fn(), cancelOperation: vi.fn(), rerunObjectify: vi.fn(), useBoxes: vi.fn(),
  };
}

const labels = (actions: ReturnType<typeof stepActions>) => actions.map((action) => `${action.stageId}:${action.label}`);

describe("step actions from the pipeline next action (T-061)", () => {
  it("asks to confirm the metric scale on the metric step", () => {
    expect(labels(stepActions(view("confirm_metric", "ST-METRIC-CANONICALIZE"), handlers(), false))).toEqual(["ST-METRIC-CANONICALIZE:Xác nhận tỉ lệ mét"]);
  });
  it("shows the anonymized frames on the review step", () => {
    expect(labels(stepActions(view("review_anonymization", "ST-ANONYMIZATION-REVIEW"), handlers(), false))).toEqual(["ST-ANONYMIZATION-REVIEW:Xem bản đã che"]);
  });
  it("offers retry on the failed stage", () => {
    const failed = view("retry_job", null, { progress: { ...view("retry_job", null).progress, status: "FAILED", error: { stage_id: "ST-CAMERA-POSE", error_code: "COLMAP_TIMEOUT", human_message: "", retryable: true } } as PipelineView["progress"] });
    expect(labels(stepActions(failed, handlers(), false))).toEqual(["ST-CAMERA-POSE:Thử lại"]);
  });
  it("opens the Studio to review objects before building meshes", () => {
    expect(labels(stepActions(view("review_objects", "ST-OBJECT-CONFIRM"), handlers(), false))).toEqual(["ST-OBJECT-CONFIRM:Mở để duyệt"]);
  });
  it("offers fixing regions and retrying the mesh build after a failure", () => {
    expect(labels(stepActions(view("retry_geometry", "ST-SCENE-DECOMPOSE"), handlers(), false))).toEqual([
      "ST-SCENE-DECOMPOSE:Mở để sửa vùng",
      "ST-SCENE-DECOMPOSE:Thử lại Tạo mesh",
    ]);
  });
  it("offers candidate boxes only when object extraction needs a choice", () => {
    expect(labels(stepActions(view("choose_object_method", "ST-OBJECT-EXTRACT"), handlers(), false))).toEqual([
      "ST-OBJECT-EXTRACT:Chạy lại tách theo vật",
      "ST-OBJECT-EXTRACT:Dùng hộp ứng viên",
    ]);
    expect(labels(stepActions(view("create_package", null), handlers(), false))).toEqual([]);
  });
  it("shows cancel while a scene operation runs", () => {
    const running = view("wait_system", "ST-SCENE-DECOMPOSE", { steps: [step("ST-SCENE-DECOMPOSE", "running")] });
    expect(labels(stepActions(running, handlers(), false))).toEqual(["ST-SCENE-DECOMPOSE:Hủy yêu cầu"]);
  });
  it("has no buttons without handlers", () => {
    expect(stepActions(view("review_objects", "ST-OBJECT-CONFIRM"), {}, false)).toEqual([]);
  });
});

describe("step metadata", () => {
  it("knows every step the backend can send", () => {
    for (const id of ["ST-ANONYMIZATION-REVIEW", "ST-OBJECT-CONFIRM", "ST-SCENE-DECOMPOSE", "ST-LIDAR-ODOMETRY"] as StageId[]) {
      expect(stageMeta(id)?.title).toBeTruthy();
    }
  });
});
