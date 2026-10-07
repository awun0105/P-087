/**
 * Mirror của Pydantic schema cho API product.
 *
 * DO NOT hand-edit field names or widen enums to silence TypeScript. Mỗi union ở
 * đây được sinh từ enum thật của backend; nếu backend đổi, hãy cập nhật cả hai và
 * chạy `tests/contract-mirror.test.ts` để so từng field.
 *
 * Nguồn: `src/models/contracts/{manifests,scene,artifacts,coordinates,release,validation}.py`
 * và `src/api/schemas.py`.
 */

// ── Enums, mirror StrEnum của backend ────────────────────────────────────────

/** src/models/contracts/manifests.py StageId — 20 stage, không thêm bớt. */
export const STAGE_IDS = [
  "ST-INPUT-VALIDATE",
  "ST-PRIVACY-GATE",
  "ST-FRAME-EXTRACT",
  "ST-CAMERA-POSE",
  "ST-VISUAL-RECON",
  "ST-RGB-GEOMETRY",
  "ST-LIDAR-INGEST",
  "ST-RGB-LIDAR-ALIGN",
  "ST-METRIC-CANONICALIZE",
  "ST-OBJECT-EXTRACT",
  "ST-OBJECT-ASSOC",
  "ST-OBJECT-CONFIRM",
  "ST-SCENE-DECOMPOSE",
  "ST-COLLIDER",
  "ST-EDIT",
  "ST-PREFLIGHT",
  "ST-CANDIDATE-BUILD",
  "ST-ISAAC-VALIDATE",
  "ST-REVIEW",
  "ST-RELEASE",
] as const;
export type StageId = (typeof STAGE_IDS)[number];

/** src/models/contracts/manifests.py StageStatus. Không có SKIPPED. */
export const STAGE_STATUSES = [
  "QUEUED",
  "RUNNING",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
] as const;
export type StageStatus = (typeof STAGE_STATUSES)[number];

/** src/models/contracts/artifacts.py ArtifactDataClass — đủ 4, kể cả evaluation_only. */
export const ARTIFACT_DATA_CLASSES = [
  "product_input",
  "derived",
  "ground_truth",
  "evaluation_only",
] as const;
export type ArtifactDataClass = (typeof ARTIFACT_DATA_CLASSES)[number];
/** `ProductDataClass` — chỉ 2, và đây là ranh giới product/prediction. */
export type ProductDataClass = Extract<ArtifactDataClass, "product_input" | "derived">;

/** `src/models/contracts/release.py` ApprovalDecision — chỉ APPROVE/REJECT, không PENDING. */
export type ReviewDecision = "APPROVE" | "REJECT";

/** `src/models/contracts/validation.py` RuleResult. */
export const RULE_RESULTS = ["PASS", "FAIL", "ERROR"] as const;
export type RuleResult = (typeof RULE_RESULTS)[number];

/** `src/models/contracts/validation.py` ObservedPathResult. */
export const PATH_RESULTS = ["CLEAR", "BLOCKED", "ERROR"] as const;
export type ObservedPathResult = (typeof PATH_RESULTS)[number];

/** `src/models/contracts/manifests.py` SourceType. */
export type SourceType = "dataset" | "upload";

/** `src/models/contracts/manifests.py` PrivacyInspectionScope. */
export type PrivacyInspectionScope = "sampled" | "all_selected_frames" | "approved_copy";

/** `src/models/contracts/coordinates.py` — hẹp, vì viewer dựng scene theo đúng convention này. */
export interface CoordinateSystemInfo {
  unit: "meter";
  up_axis: "Z";
  handedness: "right";
  world_frame: string;
}

// ── Shared contract shapes ───────────────────────────────────────────────────

/** `src/models/contracts/artifacts.py` ArtifactRef. */
export interface ArtifactRef {
  artifact_type: string;
  schema_version: string;
  artifact_uri: string;
  artifact_checksum: string;
  data_class: ArtifactDataClass;
  producer_stage: string;
  job_id?: string | null;
  source_provenance?: Record<string, unknown> | null;
}

/** `src/models/contracts/artifacts.py` ProductArtifactRef. */
export interface ProductArtifactRef extends ArtifactRef {
  data_class: ProductDataClass;
}

/** `src/models/contracts/coordinates.py` Transform. */
export interface Transform {
  semantics: "parent_from_local";
  parent_frame: string;
  local_frame: string;
  translation_xyz: [number, number, number];
  rotation_quaternion_xyzw: [number, number, number, number];
  quaternion_order: "xyzw";
  angle_unit: "radian";
}

/** `src/models/contracts/manifests.py` ExecutionError — có `details` mà bản cũ thiếu. */
export interface ExecutionError {
  stage_id: StageId;
  error_code: string;
  human_message: string;
  retryable: boolean;
  details?: Record<string, unknown> | null;
}

export const JOB_STATUSES = ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

/** `src/models/contracts/manifests.py` PrivacyResult. Bản cũ đoán sai hoàn toàn. */
export const PRIVACY_RESULTS = ["PRELIMINARY_SCREENED", "VERIFIED_ANONYMIZED", "QUARANTINED"] as const;
export type PrivacyResult = (typeof PRIVACY_RESULTS)[number];

/**
 * `src/models/contracts/manifests.py` StageArtifact — có `error`, nên timeline phải
 * hiện được lỗi thật thay vì im lặng.
 */
export interface StageArtifact {
  stage_id: StageId;
  status: StageStatus;
  artifact_type: string | null;
  artifact_uri: string | null;
  artifact_checksum: string | null;
  data_class: ProductDataClass | null;
  started_at: string | null;
  completed_at: string | null;
  error: ExecutionError | null;
}

/** `src/services/orchestration/jobs/transitions.py` ALLOWED_TRANSITIONS. */
export const JOB_TRANSITIONS: Record<JobStatus, readonly JobStatus[]> = {
  QUEUED: ["RUNNING", "CANCELLED"],
  RUNNING: ["SUCCEEDED", "FAILED", "CANCELLED"],
  SUCCEEDED: [],
  FAILED: ["QUEUED"],
  CANCELLED: [],
};

export interface ProjectResponse {
  project_id: string;
  name: string;
  source_type: SourceType;
  input_manifest_checksum: string;
  source_rights_attestation: Record<string, unknown>;
  privacy: PrivacyStateResponse;
  /** Chỉ có với project tạo từ video upload (Studio MVP). */
  input_video?: { original_name: string; media_type: string; size_bytes: number } | null;
  created_at?: string | null;
  /** Người tạo scene; null với project cũ hoặc khi không bật đăng nhập. */
  created_by?: { user_id: string; display_name: string } | null;
}

export interface ProjectListResponse {
  projects: ProjectResponse[];
}

export interface PrivacyStateResponse {
  project_id: string;
  result: PrivacyResult;
  input_manifest_checksum: string;
  inspection_scope: PrivacyInspectionScope;
  unresolved_finding_count: number;
  dispatch_allowed: boolean;
  block_reason: string | null;
}

/** `src/models/contracts/manifests.py` JobManifest. */
export interface JobManifest {
  schema_version: string;
  job_id: string;
  project_id: string;
  status: JobStatus;
  current_stage: StageId | null;
  seed: number;
  scene_revision: string;
  stage_artifacts: StageArtifact[];
  input_manifest_checksum: string;
  config_checksum: string;
  runtime_manifest_checksum: string;
  job_manifest_checksum: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobListResponse {
  jobs: JobManifest[];
}

/** `src/api/schemas.py` JobCreateRequest — `project_id` lấy từ path, không gửi body. */
export interface JobCreateRequest {
  scene_revision?: string;
}

/** `src/models/contracts/scene.py` SceneObjectState. */
export type SceneObjectState = "CANDIDATE" | "CONFIRMED";

export interface ArtifactListResponse {
  job_id: string;
  artifacts: ProductArtifactRef[];
  excluded_artifact_count: number;
}

/** `src/services/orchestration/jobs/models.py` JobAttemptRecord. */
export interface JobAttemptRecord {
  attempt: number;
  status: JobStatus;
  current_stage: StageId;
  recorded_at: string;
  job_manifest_uri: string | null;
  job_manifest_checksum: string | null;
  actual_frame_count: number | null;
  stage_started_at: string | null;
  preview_verified_at: string | null;
}

export interface JobAttemptListResponse {
  job_id: string;
  attempts: JobAttemptRecord[];
}

/** `src/models/contracts/scene.py` ColliderSpec — `provenance` là bắt buộc. */
export interface ColliderSpec {
  collider_id: string;
  collider_type: string;
  dimensions_xyz_m: [number, number, number] | null;
  local_transform: Transform;
  geometry_ref: ArtifactRef | null;
  parameters: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

/**
 * `src/models/contracts/scene.py` SceneObject.
 *
 * Bản cũ thiếu 5 field: `visual_ref`, `asset_ref`, `primitive_dimensions_xyz_m`,
 * `semantic_class`, `tags`. Hai field đầu là thứ làm một object `user_added` hợp lệ
 * theo validator `scene.py` (cần `asset_ref` **hoặc** `primitive_dimensions_xyz_m`),
 * nên thiếu chúng là frontend không diễn đạt được object do chính PRODUCT-07A tạo.
 */
export interface SceneObject {
  id: string;
  name: string;
  origin: string;
  state: SceneObjectState;
  active: boolean;
  transform: Transform;
  local_frame: string;
  geometry_ref: ArtifactRef;
  visual_ref: ArtifactRef | null;
  asset_ref: ArtifactRef | null;
  primitive_dimensions_xyz_m: [number, number, number] | null;
  semantic_class: string | null;
  tags: string[];
  collider: ColliderSpec | null;
  provenance: Record<string, unknown>;
  /** Pipeline v2 (ADR 0007); backend không ghi field khi rỗng nên có thể vắng mặt. */
  physics?: ObjectPhysics | null;
  /** Ownership collision bất biến của geometry nguồn; vắng mặt ở SceneIR legacy. */
  source_collision?: SourceCollisionRegion | null;
}

/** Source pose/region gốc dùng để rebuild collision sau các thao tác edit. */
export interface SourceCollisionRegion {
  schema_version: "1.0";
  object_id: string;
  source_geometry_ref: ProductArtifactRef;
  extraction_revision: string;
  source_transform: Transform;
  region_kind: "triangle_indices" | "source_obb";
  region_ref?: ProductArtifactRef | null;
  source_obb_dimensions_xyz_m?: [number, number, number] | null;
}

/** `src/models/contracts/scene.py` MassSource — số khối lượng đến từ đâu. */
export type MassSource = "catalog_default" | "catalog_density" | "user" | "asset";

/** `src/models/contracts/scene.py` ObjectPhysics — RigidBody/Mass/Physics Material cho Isaac. */
export interface ObjectPhysics {
  dynamic: boolean;
  mass_kg: number | null;
  mass_source: MassSource | null;
  density_kg_m3: number | null;
  static_friction: number;
  dynamic_friction: number;
  restitution: number;
  provenance: Record<string, unknown>;
}

/** `src/models/contracts/scene.py` SceneEnvironment — bản cũ thiếu `visual_ref`. */
export interface SceneEnvironment {
  visual_ref: ArtifactRef | null;
  geometry_ref: ArtifactRef;
  collider_ref: ArtifactRef | null;
  /** Bản 3DGS gốc (PLY) cho bộ xuất USD; vắng mặt ở SceneIR cũ. */
  visual_master_ref?: ArtifactRef | null;
}

export interface SceneIR {
  artifact_type: string;
  schema_version: string;
  scene_id: string;
  scene_revision: string;
  coordinate_system: CoordinateSystemInfo;
  metric_scale: { status: "UNCONFIRMED" | "CONFIRMED"; meters_per_unit: number | null };
  environment: SceneEnvironment;
  objects: SceneObject[];
  provenance: Record<string, unknown>;
  scene_ir_checksum: string;
}

/**
 * Trạng thái visual của scene. `brush_compatibility_proof=false` nghĩa là visual
 * hiện tại **không** phải bằng chứng AC-11 và không được báo cáo như vậy.
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
  supersedes_revision: string | null;
  scene_uri: string;
  scene_checksum: string;
  scene_revision: string;
  scene: SceneIR;
  visual: VisualBinding;
}

export interface SceneObjectCommand {
  object_id: string;
  translation_xyz?: [number, number, number];
  rotation_quaternion_xyzw?: [number, number, number, number];
}

export interface SceneEditCommand {
  expected_scene_revision: string;
  edits: SceneObjectCommand[];
}

export interface SceneEditResponse {
  job_id: string;
  previous_scene_revision: string;
  scene_revision: string;
  scene_uri: string;
  scene_checksum: string;
  scene: SceneIR;
  visual: VisualBinding;
}

/** `src/models/contracts/validation.py` ValidationCheck / PathResult. */
export interface ValidationCheck {
  check_id: string;
  result: RuleResult;
  message: string | null;
  evidence_refs: ArtifactRef[];
}

export interface PathResult {
  pair_id: string;
  result: ObservedPathResult;
  message: string | null;
  evidence_refs: ArtifactRef[];
}

/** `src/models/contracts/release.py` ApprovalRecord. */
export interface ApprovalRecord {
  schema_version: string;
  decision: ReviewDecision;
  reviewer_id: string;
  decided_at: string;
  reason: string | null;
  accepted_warning_ids: string[];
  candidate_checksum: string;
  validation_report_checksum: string;
  record_checksum: string;
}

/** `src/models/contracts/validation.py` ValidationReport. */
export interface ValidationReport {
  schema_version: string;
  validator_version: string;
  candidate_checksum: string;
  overall_result: RuleResult;
  checks: ValidationCheck[];
  path_results: PathResult[];
  environment_versions: Record<string, string>;
  report_checksum: string;
}

/**
 * `src/api/schemas.py` ValidationStateResponse — lồng `report`, không phẳng. Bản cũ
 * phẳng `checks`/`path_results` lên top level nên mọi mức đọc phải đoán.
 */
export interface ValidationStateResponse {
  job_id: string;
  report: ValidationReport;
  report_checksum_verified: boolean;
  isaac_runtime_proof: boolean;
}

/**
 * `src/api/schemas.py` ReviewStateResponse.
 *
 * `approval` là **bắt buộc** trong Pydantic và chỉ có `APPROVE`/`REJECT` — backend
 * không có trạng thái "PENDING". Bản cũ khai `decision: "PENDING" | "APPROVE" |
 * "REJECT"`, và UI được viết theo giá trị bịa đó, nên nút Approve/Reject không bao
 * giờ hiện. "Chưa có approval" là khi `approval` vắng mặt, không phải khi decision
 * là PENDING.
 *
 * `synthetic_authorization=true` nghĩa là approval đến từ fixture, **không phải**
 * uỷ quyền Reviewer thật — UI bắt buộc phải hiện cờ này.
 */
export interface ReviewStateResponse {
  job_id: string;
  approval?: ApprovalRecord;
  synthetic_authorization: boolean;
  note: string;
}

/**
 * Alias giữ tên cũ. `api.ts` trước đây dùng tên ngắn hơn backend (`JobList` thay vì
 * `JobListResponse`), nên call site cũ vẫn dùng được. Tên canonical là tên Pydantic;
 * các alias này sẽ bị xoá khi call site chuyển hết.
 */
export type ArtifactList = ArtifactListResponse;
export type JobList = JobListResponse;
export type ProjectList = ProjectListResponse;
export type Project = ProjectResponse;
export type PrivacyState = PrivacyStateResponse;
export type ValidationState = ValidationStateResponse;
export type ReviewState = ReviewStateResponse;
export type JobAttempt = JobAttemptRecord;
export type JobAttemptList = JobAttemptListResponse;
export type ColliderType = string;
/** `TransformEdit` của bản cũ là lệnh transform, không phải `Transform` của SceneIR. */
export type TransformEdit = SceneObjectCommand;

/** `src/services/orchestration/jobs/models.py` TransitionRequest. */
export interface TransitionRequest {
  target_status: JobStatus;
  current_stage?: StageId | null;
}

export interface ApiErrorBody {
  detail: string;
}
