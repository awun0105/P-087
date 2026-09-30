/**
 * Mirror của `src/api/studio/`, `jobs/progress.py`, `samples/models.py`.
 *
 * Dữ liệu từ API được parse tại biên (không cast mù) để UI không hiển thị trạng
 * thái sai khi backend đổi shape.
 */

import type { JobManifest, StageId } from "@/lib/contracts/api";

export type VideoMediaType = "video/mp4" | "video/quicktime";

export type UploadMediaType = VideoMediaType | "application/x-ply" | "application/zip";

/** Loại đầu vào máy chủ nhận diện theo nội dung (ADR 0004). */
export type InputKind = "rgb_video" | "gaussian_ply" | "gaussian_ply_colmap";

export interface InputDetection {
  kind: InputKind;
  gaussian: { gaussian_count: number; sh_degree: number; encoding: string } | null;
  ply_member: string | null;
  colmap_dir: string | null;
  colmap_format: "bin" | "txt" | null;
}

export interface UploadRecord {
  upload_id: string;
  original_name: string;
  media_type: UploadMediaType;
  size_bytes: number;
  checksum: string;
  artifact_uri: string;
  received_at: string;
  project_ids: string[];
  input_kind?: InputKind;
  detection?: InputDetection | null;
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

export type StageState = "pending" | "running" | "waiting" | "succeeded" | "failed" | "cancelled";

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
  /** Pipeline đang chờ người dùng làm gì (vd xác nhận tỉ lệ mét sau preview). */
  waiting_for?: "metric_confirmation" | null;
  error: ExecutionErrorView | null;
}

/** Nguồn số đo: người dùng đo ngoài đời, hoặc LiDAR của dataset mẫu (ADR 0004 §6). */
export type DistanceSource = "user_measured" | "lidar_demo";

/** Điểm chọn trên 3DGS (hệ gốc file, đơn vị SfM) + số đo A–B, C–D. Khớp `UserMetricInput`. */
export interface MetricInput {
  floor_points: [MetricPoint, MetricPoint, MetricPoint];
  point_a: MetricPoint;
  point_b: MetricPoint;
  distance_m: number;
  check_a: MetricPoint;
  check_b: MetricPoint;
  check_distance_m: number;
  distance_source: DistanceSource;
}

export type MetricPoint = [number, number, number];

/** Số liệu xem trước để người dùng tự kiểm; chưa phải xác nhận. Khớp `MetricPreviewView`. */
export interface MetricPreview {
  preview_checksum: string;
  scale_m_per_sfm_unit: number;
  floor_residual_m: number;
  measured_distance_m: number;
  camera_height_min_m: number;
  camera_height_max_m: number;
  distance_source: DistanceSource;
  check_measured_m: number;
  check_error_m: number;
  check_tolerance_m: number;
  check_passed: boolean;
  warnings: string[];
}

/** Một phép đo LiDAR: điểm LiDAR đã bắt và khoảng cách (mét). Khớp `LidarDistance`. */
export interface LidarDistance {
  clicked_world: [MetricPoint, MetricPoint];
  lidar_points_m: [MetricPoint, MetricPoint];
  snap_offsets_m: [number, number];
  /** Điểm dùng để đo: bắt vào LiDAR, hay vị trí theo căn chỉnh khi LiDAR không phủ tới. */
  point_sources: ["lidar_surface" | "trajectory_alignment", "lidar_surface" | "trajectory_alignment"];
  distance_m: number;
}

/** 7 điểm hệ thống tự chọn trên sàn LiDAR (A, B, C, D, 3 điểm sàn) + số đo (dataset mẫu). */
export interface DemoSelection {
  points: MetricPoint[];
  measurements: LidarMeasurements;
}

export interface LidarMeasurements {
  anchor: LidarDistance;
  check: LidarDistance;
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

export type ParamValue = number | string;

export interface ParameterSpec {
  key: string;
  group: "sampling" | "colmap" | "brush";
  label: string;
  description: string;
  kind: "number" | "integer" | "choice";
  unit: string | null;
  min: number | null;
  max: number | null;
  step: number | null;
  choices: { value: string; label: string }[] | null;
}

export interface MachineCapability {
  worker_id: string;
  measured_at: string;
  gpu_name: string | null;
  vram_total_gb: number | null;
  cpu_count: number;
  ram_total_gb: number;
  disk_free_gb: number;
}

export type ResourceStatus = "ok" | "warn" | "danger" | "unknown";

export interface ResourceEstimate {
  resource: "vram" | "ram" | "disk";
  required_gb: number;
  available_gb: number | null;
  status: ResourceStatus;
  message: string;
}

export interface ProcessingEvaluation {
  resources: ResourceEstimate[];
  parameters: { key: string; status: ResourceStatus; message: string | null }[];
  blocking: boolean;
  note: string;
}

export interface ProcessingOptions {
  profile_id: string;
  parameters: ParameterSpec[];
  presets: { minimum_quality: Record<string, ParamValue>; maximum: Record<string, ParamValue>; machine_maximum: Record<string, ParamValue> };
  capability: MachineCapability | null;
  default_evaluation: ProcessingEvaluation;
  resource_note: string;
}

export interface SampleSummary {
  sample_id: string;
  title: string;
  description: string;
  origin: "pipeline_job" | "smoke_run";
  source: { dataset: string; sequence: string; note: string };
  cover: string | null;
  video: DemoFile | null;
  frame_count: number | null;
  total_seconds: number | null;
  has_processing: boolean;
  machine: Record<string, string>;
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
  processing?: Record<string, ParamValue> | null;
  machine?: Record<string, string>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const STAGE_STATES: readonly StageState[] = ["pending", "running", "waiting", "succeeded", "failed", "cancelled"];
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

const METRIC_NUMBERS = [
  "scale_m_per_sfm_unit", "floor_residual_m", "measured_distance_m", "camera_height_min_m", "camera_height_max_m",
  "check_measured_m", "check_error_m", "check_tolerance_m",
] as const;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Số liệu xem trước phải đủ và hữu hạn; không hiển thị scale từ response lạ. */
export function parseMetricPreview(value: unknown): MetricPreview {
  if (!isRecord(value) || typeof value.preview_checksum !== "string" || !Array.isArray(value.warnings) ||
      !value.warnings.every((warning) => typeof warning === "string") ||
      typeof value.check_passed !== "boolean" ||
      (value.distance_source !== "user_measured" && value.distance_source !== "lidar_demo") ||
      !METRIC_NUMBERS.every((key) => isFiniteNumber(value[key]))) {
    throw new Error("Bản xem trước tỉ lệ từ backend không hợp lệ");
  }
  return value as unknown as MetricPreview;
}

function isLidarDistance(value: unknown): value is LidarDistance {
  return isRecord(value) && isFiniteNumber(value.distance_m) && value.distance_m > 0 &&
    Array.isArray(value.snap_offsets_m) && value.snap_offsets_m.length === 2 && value.snap_offsets_m.every(isFiniteNumber);
}

/** Số đo LiDAR phải dương, hữu hạn trước khi điền vào ô khoảng cách. */
export function parseLidarMeasurements(value: unknown): LidarMeasurements {
  if (!isRecord(value) || !isLidarDistance(value.anchor) || !isLidarDistance(value.check)) {
    throw new Error("Số đo LiDAR từ backend không hợp lệ");
  }
  return value as unknown as LidarMeasurements;
}

/** Bộ điểm demo phải đủ 7 điểm hữu hạn và số đo hợp lệ trước khi vẽ lên scene. */
export function parseDemoSelection(value: unknown): DemoSelection {
  if (!isRecord(value) || !Array.isArray(value.points) || value.points.length !== 7 ||
      !value.points.every((point) => Array.isArray(point) && point.length === 3 && point.every(isFiniteNumber))) {
    throw new Error("Bộ điểm demo từ backend không hợp lệ");
  }
  parseLidarMeasurements(value.measurements);
  return value as unknown as DemoSelection;
}

/** Lớp xem được của một bước (ADR 0005). Khớp `StageView` backend. */
export interface StageView {
  stage_id: string;
  kind: "frames" | "cameras" | "gaussian" | "mesh";
  title: string;
  note: string;
  unit: "meter" | "arbitrary";
  refs: { artifact_uri: string; artifact_checksum: string; artifact_type: string }[];
  cameras: { frame_id: number; center: [number, number, number]; rotation_xyzw: [number, number, number, number] }[];
}

const VIEW_KINDS: readonly StageView["kind"][] = ["frames", "cameras", "gaussian", "mesh"];

/** Danh sách lớp xem: kind phải biết, ref phải có URI/checksum, camera phải hữu hạn. */
export function parseStageViews(value: unknown): StageView[] {
  if (!isRecord(value) || !Array.isArray(value.views)) throw new Error("Danh sách kết quả từng bước không hợp lệ");
  for (const view of value.views) {
    if (!isRecord(view) || !VIEW_KINDS.includes(view.kind as StageView["kind"]) || typeof view.title !== "string" ||
        !Array.isArray(view.refs) || !Array.isArray(view.cameras) ||
        !view.refs.every((ref) => isRecord(ref) && typeof ref.artifact_uri === "string" && typeof ref.artifact_checksum === "string") ||
        !view.cameras.every((camera) => isRecord(camera) && Array.isArray(camera.center) && camera.center.every(isFiniteNumber))) {
      throw new Error("Một lớp xem không hợp lệ");
    }
  }
  return value.views as unknown as StageView[];
}

/** Một cột của màn hình so sánh 3 hướng tỉ lệ (ADR 0004 §5). Khớp `ModeResult`. */
export interface ModeResult {
  mode: "rgb_only" | "user_anchor" | "lidar";
  title: string;
  status: "mock" | "measured" | "missing";
  note: string;
  steps: string[];
  scale_m_per_sfm_unit: number | null;
  camera_height_mean_m: number | null;
  camera_height_range_m: [number, number] | null;
}

export interface ModeComparison {
  job_id: string;
  modes: ModeResult[];
  difference: {
    scale_diff_percent: number;
    floor_tilt_deg: number;
    camera_height_diff_m: number;
    check_segment_user_m: number | null;
    check_segment_lidar_m: number | null;
    check_segment_error_m: number | null;
  } | null;
  lidar_ground_truth_assisted: boolean;
}

/** Cột "mock" không bao giờ được mang số (không hiển thị số giả). */
export function parseModeComparison(value: unknown): ModeComparison {
  if (!isRecord(value) || !Array.isArray(value.modes) || value.modes.length !== 3) {
    throw new Error("So sánh 3 hướng từ backend không hợp lệ");
  }
  for (const mode of value.modes) {
    if (!isRecord(mode) || typeof mode.title !== "string" || !["mock", "measured", "missing"].includes(String(mode.status))) {
      throw new Error("Một hướng so sánh không hợp lệ");
    }
    if (mode.status !== "measured" && mode.scale_m_per_sfm_unit != null) throw new Error("Hướng chưa đo không được có số tỉ lệ");
    if (mode.status === "measured" && !isFiniteNumber(mode.scale_m_per_sfm_unit)) throw new Error("Thiếu tỉ lệ đo được");
  }
  return value as unknown as ModeComparison;
}

/** Scene import từ file 3DGS, chỉ xem/chỉnh sửa (ADR 0004 §3). Khớp `ImportedScene`. */
export interface ImportedScene {
  import_id: string;
  upload_id: string;
  name: string;
  input_kind: "gaussian_ply" | "gaussian_ply_colmap";
  status: "PACKAGING" | "READY" | "FAILED";
  delivery_ref: { artifact_uri: string; artifact_checksum: string } | null;
  error: string | null;
  created_at: string;
}
