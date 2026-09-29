/**
 * Mirror của `src/api/routes_studio.py`, `jobs/progress.py`, `demo/models.py`.
 *
 * Dữ liệu từ API được parse tại biên (không cast mù) để UI không hiển thị trạng
 * thái sai khi backend đổi shape.
 */

import type { JobManifest, StageId } from "@/lib/contracts/api";

export type VideoMediaType = "video/mp4" | "video/quicktime";

export interface UploadRecord {
  upload_id: string;
  original_name: string;
  media_type: VideoMediaType;
  size_bytes: number;
  checksum: string;
  artifact_uri: string;
  received_at: string;
  project_ids: string[];
}

export type DataOrigin = "public_or_synthetic" | "self_collected_no_pii" | "anonymized";

export interface SourceRightsAttestation {
  data_origin: DataOrigin;
  declared_owner: string;
  declared_purpose: string;
  rights_to_use_confirmed: boolean;
  anonymization_confirmed: boolean;
  retention_acknowledged: boolean;
}

export interface StudioPrivacy {
  result: "PRELIMINARY_SCREENED" | "VERIFIED_ANONYMIZED" | "QUARANTINED";
  dispatch_allowed: boolean;
  block_reason: string | null;
  privacy_mode: "qa_verified" | "self_attested";
}

export interface StudioProject {
  project_id: string;
  name: string;
  source_type: "upload" | "dataset";
  privacy: StudioPrivacy;
  input_video: { original_name: string; media_type: VideoMediaType; size_bytes: number } | null;
  created_at: string | null;
}

export interface SceneSummary {
  project: StudioProject;
  latest_job: JobManifest | null;
  preview_ready: boolean;
}

export interface SceneFromUpload {
  project: StudioProject;
  job: JobManifest;
}

export type StageState = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export interface ExecutionErrorView {
  error_code: string;
  stage_id: StageId;
  human_message: string;
  retryable: boolean;
}

export interface StageProgress {
  stage_id: StageId;
  state: StageState;
  started_at: string | null;
  completed_at: string | null;
  error: ExecutionErrorView | null;
}

export interface JobProgress {
  job_id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  current_stage: StageId;
  attempt: number;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  stages: StageProgress[];
  preview_ready: boolean;
  error: ExecutionErrorView | null;
}

export interface DemoFile {
  name: string;
  media_type: string;
  size_bytes: number;
  checksum: string;
}

export interface DemoStage {
  stage_id: StageId;
  duration_seconds: number | null;
  summary: string;
}

export interface DemoManifest {
  schema_version: "1.0";
  demo_id: string;
  title: string;
  description: string;
  origin: "pipeline_job" | "smoke_run";
  source: { dataset: string; sequence: string; note: string };
  produced_at: string;
  provenance: Record<string, string>;
  stages: DemoStage[];
  video: DemoFile | null;
  frames: DemoFile[];
  frame_count: number | null;
  splat: DemoFile;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const STAGE_STATES: readonly StageState[] = ["pending", "running", "succeeded", "failed", "cancelled"];
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

/** Kiểm các field UI dùng để vẽ tiến trình; shape lạ → ném lỗi thay vì hiển thị sai. */
export function parseJobProgress(value: unknown): JobProgress {
  if (!isRecord(value) || typeof value.job_id !== "string" || !Array.isArray(value.stages) ||
      typeof value.preview_ready !== "boolean" || typeof value.status !== "string") {
    throw new Error("Tiến trình job từ backend không hợp lệ");
  }
  for (const stage of value.stages) {
    if (!isRecord(stage) || typeof stage.stage_id !== "string" ||
        !STAGE_STATES.includes(stage.state as StageState)) {
      throw new Error("Stage trong tiến trình không hợp lệ");
    }
  }
  return value as unknown as JobProgress;
}

/** Tên file demo phải phẳng (không path) vì được ghép vào URL. */
export function parseDemoManifest(value: unknown): DemoManifest {
  if (!isRecord(value) || value.schema_version !== "1.0" || !isRecord(value.splat) ||
      !Array.isArray(value.frames) || !Array.isArray(value.stages) ||
      (value.origin !== "pipeline_job" && value.origin !== "smoke_run")) {
    throw new Error("Demo bundle không hợp lệ");
  }
  const files = [value.splat, ...(value.video ? [value.video] : []), ...value.frames];
  if (!files.every((file) => isRecord(file) && typeof file.name === "string" && SAFE_NAME.test(file.name))) {
    throw new Error("Tên file demo không hợp lệ");
  }
  return value as unknown as DemoManifest;
}
