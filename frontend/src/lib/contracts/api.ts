/**
 * Type mirror của product API (EX-PRODUCT).
 *
 * Nguồn sự thật là Pydantic contract ở `src/models/contracts/**` và DTO ở
 * `src/api/schemas.py`. File này chỉ chép lại shape để TypeScript kiểm tra được
 * lúc build — không định nghĩa thêm field và không nới lỏng field nào.
 *
 * Bất biến: mọi ref chỉ mang `artifact://jobs/<job_id>/<path>` + checksum.
 * Không có type nào ở đây chở đường dẫn filesystem.
 */

export const JOB_STATUSES = ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

/** Trạng thái job còn đi tiếp được hay không (khớp ALLOWED_TRANSITIONS ở backend). */
export const JOB_TRANSITIONS: Record<JobStatus, readonly JobStatus[]> = {
  QUEUED: ["RUNNING", "CANCELLED"],
  RUNNING: ["SUCCEEDED", "FAILED", "CANCELLED"],
  SUCCEEDED: [],
  FAILED: ["QUEUED"],
  CANCELLED: [],
};

export const PRIVACY_RESULTS = [
  "PRELIMINARY_SCREENED",
  "VERIFIED_ANONYMIZED",
  "QUARANTINED",
] as const;
export type PrivacyResult = (typeof PRIVACY_RESULTS)[number];

export type ArtifactDataClass = "product_input" | "derived";
export type StageId = string;

export interface ArtifactRef {
  artifact_type: string;
  schema_version: string;
  artifact_uri: string;
  artifact_checksum: string;
  data_class: ArtifactDataClass;
  producer_stage: StageId;
  job_id: string | null;
}

export interface PrivacyState {
  result: PrivacyResult;
  input_manifest_checksum: string;
  inspection_scope: string;
  unresolved_finding_count: number;
  dispatch_allowed: boolean;
  block_reason: string | null;
}

export interface Project {
  project_id: string;
  name: string;
  source_type: string;
  input_manifest_checksum: string;
  source_rights_attestation: Record<string, unknown>;
  privacy: PrivacyState;
}

export interface ProjectList {
  projects: Project[];
}

export interface ExecutionError {
  error_code: string;
  stage_id: string;
  human_message: string;
  retryable: boolean;
}

export interface StageArtifact {
  stage_id: StageId;
  status: string;
  artifact_type: string | null;
  artifact_uri: string | null;
  artifact_checksum: string | null;
  data_class: ArtifactDataClass | null;
  started_at: string | null;
  completed_at: string | null;
  error: ExecutionError | null;
}

/** Một lần chạy. `job_manifest_uri` là revision đã persist cho lần chạy đó. */
export interface JobAttempt {
  attempt: number;
  status: JobStatus;
  current_stage: StageId;
  recorded_at: string;
  job_manifest_uri: string | null;
  job_manifest_checksum: string | null;
  error: ExecutionError | null;
}

export interface JobManifest {
  schema_version: string;
  job_id: string;
  project_id: string;
  scene_revision: string;
  status: JobStatus;
  input_manifest_checksum: string;
  config_checksum: string;
  runtime_manifest_checksum: string;
  seed: number | null;
  started_at: string;
  completed_at: string | null;
  current_stage: StageId;
  stage_artifacts: StageArtifact[];
  job_manifest_checksum: string;
}

export interface JobList {
  project_id: string;
  jobs: JobManifest[];
}

export interface JobAttemptList {
  job_id: string;
  attempts: JobAttempt[];
}

export interface ArtifactList {
  job_id: string;
  artifacts: ArtifactRef[];
  excluded_artifact_count: number;
}

// ── SceneIR (PRODUCT-06) ────────────────────────────────────────────────────

export interface Transform {
  semantics: "parent_from_local";
  parent_frame: string;
  local_frame: string;
  translation_xyz: [number, number, number];
  rotation_quaternion_xyzw: [number, number, number, number];
}

export type ColliderType = "AABB" | "OBB" | "CONVEX_HULL" | "SIMPLIFIED_MESH";

export interface ColliderSpec {
  collider_id: string;
  collider_type: ColliderType;
  local_transform: Transform;
  dimensions_xyz_m: [number, number, number] | null;
  geometry_ref: ArtifactRef | null;
  parameters: Record<string, unknown>;
}

export interface SceneObject {
  id: string;
  name: string;
  state: "CANDIDATE" | "CONFIRMED";
  origin: "reconstructed" | "user_added";
  active: boolean;
  local_frame: string;
  transform: Transform;
  geometry_ref: ArtifactRef;
  collider: ColliderSpec | null;
  provenance: Record<string, unknown>;
}

export interface SceneEnvironment {
  geometry_ref: ArtifactRef;
  collider_ref: ArtifactRef | null;
}

export interface SceneIR {
  artifact_type: "SceneIR";
  schema_version: string;
  scene_id: string;
  scene_revision: string;
  coordinate_system: { unit: string; up_axis: string; handedness: string; world_frame: string };
  metric_scale: { status: "CONFIRMED" | "UNCONFIRMED"; meters_per_unit: number | null };
  environment: SceneEnvironment;
  objects: SceneObject[];
  provenance: Record<string, unknown>;
  scene_ir_checksum: string;
}

/**
 * Trạng thái visual của scene. `brush_compatibility_proof` là false nghĩa là
 * visual hiện tại **không** phải bằng chứng AC-11 và không được báo cáo như vậy.
 */
export interface VisualBinding {
  available: boolean;
  format: string | null;
  producer: string | null;
  producer_version: string | null;
  reference: ArtifactRef | null;
  source_input_checksum: string | null;
  brush_compatibility_proof: boolean;
  unavailable_reason: string | null;
}

export interface SceneResponse {
  job_id: string;
  scene_id: string;
  scene_revision: string;
  scene_uri: string;
  scene_checksum: string;
  supersedes_revision: string | null;
  scene: SceneIR;
  visual: VisualBinding;
}

export interface SceneEditResponse {
  job_id: string;
  previous_scene_revision: string;
  scene_revision: string;
  scene_uri: string;
  scene_checksum: string;
  scene: SceneIR;
}

// ── validation và review ────────────────────────────────────────────────────

export interface ValidationCheck {
  check_id: string;
  result: string;
  evidence_refs: ArtifactRef[];
  message: string;
}

export interface PathResult {
  pair_id: string;
  result: string;
  evidence_refs: ArtifactRef[];
  message: string;
}

export interface ValidationReport {
  schema_version: string;
  candidate_checksum: string;
  validator_version: string;
  environment_versions: Record<string, string>;
  checks: ValidationCheck[];
  path_results: PathResult[];
  overall_result: string;
  report_checksum: string;
}

export interface ValidationState {
  job_id: string;
  report: ValidationReport;
  report_checksum_verified: boolean;
  isaac_runtime_proof: boolean;
}

export type ReviewDecision = "PENDING" | "APPROVE" | "REJECT";

export interface ApprovalRecord {
  schema_version: string;
  candidate_checksum: string;
  validation_report_checksum: string;
  reviewer_id: string;
  decision: ReviewDecision;
  reason: string | null;
  decided_at: string;
  accepted_warning_ids: string[];
  record_checksum: string;
}

export interface ReviewState {
  job_id: string;
  approval: ApprovalRecord;
  synthetic_authorization: boolean;
  note: string;
}

// ── request payloads ────────────────────────────────────────────────────────

export interface TransformEdit {
  object_id: string;
  translation_xyz?: [number, number, number];
  rotation_quaternion_xyzw?: [number, number, number, number];
}

export interface SceneEditCommand {
  expected_scene_revision: string;
  edits: TransformEdit[];
}

export interface TransitionRequest {
  target_status: JobStatus;
  current_stage?: StageId;
  error?: ExecutionError;
}

export interface JobCreateRequest {
  scene_revision?: string;
}

export interface ApiErrorBody {
  detail: string;
}
