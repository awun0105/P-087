/**
 * Mirror của `src/api/studio/`, `jobs/progress.py`, `samples/models.py`.
 *
 * Dữ liệu từ API được parse tại biên (không cast mù) để UI không hiển thị trạng
 * thái sai khi backend đổi shape.
 */

import type { JobManifest, StageId } from "@/lib/contracts/api";

export type VideoMediaType = "video/mp4" | "video/quicktime";

export type UploadMediaType = VideoMediaType | "application/x-ply" | "application/x-sog" | "application/x-pcd" | "application/zip";

/** Loại đầu vào máy chủ nhận diện theo nội dung (ADR 0004; LiDAR theo ADR 0009). */
export type InputKind = "rgb_video" | "gaussian_ply" | "gaussian_ply_colmap" | "gaussian_sog" | "registered_lidar" | "lidar_scan_sequence";

/**
 * Bằng chứng gói LiDAR (ADR 0009). Gói luôn có quỹ đạo, calibration và thời điểm frame; đám mây đã đăng ký có
 * `cloud_member` + `point_count`, chuỗi scan thô có `scan_count`.
 */
export interface LidarEvidence {
  geometry_format: "ply" | "pcd";
  cloud_member: string | null;
  point_count: number | null;
  scan_count: number | null;
  pose_count: number;
  trajectory_member: string;
  calibration_member: string;
  calibration_format: "torwic_txt" | "json";
  frame_times_member: string;
  pairing: "index_in_name" | "sorted_order" | null;
}

/** Gói LiDAR gắn vào scene khi tạo (ADR 0009) cùng hai lời khai bắt buộc. */
export interface LidarAttachment {
  upload_id: string;
  trajectory_origin: "estimated" | "ground_truth";
  same_scene_confirmed: boolean;
}

export interface InputDetection {
  kind: InputKind;
  gaussian: { gaussian_count: number; sh_degree: number; encoding: string } | null;
  sog?: { format_version: 2; gaussian_count: number; sh_degree: number; model: "antialiased" | "2dgs" | null } | null;
  ply_member: string | null;
  colmap_dir: string | null;
  colmap_format: "bin" | "txt" | null;
  lidar?: LidarEvidence | null;
}

/** Người thực hiện một thao tác (tải file, tạo scene, chạy job), chụp lại lúc thao tác; null = không biết. */
export interface Actor {
  user_id: string;
  display_name: string;
  /** Role lúc snapshot được tạo; không suy ra từ role hiện tại của user. */
  role?: "guest" | "editor" | "reviewer" | null;
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
  uploaded_by?: Actor | null;
  /** Safe status only; preparation source fingerprint and verification evidence stay private. */
  video_preparation_status?: "pending" | "verified" | null;
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
  display_video_url?: string | null;
  created_at: string | null;
  created_by?: Actor | null;
  /** Mốc bản demo nếu scene được đánh dấu là bản demo. */
  demo_baseline?: DemoBaseline | null;
}

/** Mốc "bản demo gốc" của scene: revision mà nút Khôi phục bản demo đưa scene trở về. Khớp `DemoBaseline`. */
export interface DemoBaseline {
  job_id: string;
  scene_revision: string;
  marked_at: string;
  marked_by?: Actor | null;
}

/** Trạng thái bản demo của một job. Khớp `DemoState` backend. */
export interface DemoState {
  job_id: string;
  baseline: DemoBaseline | null;
  current_revision: string | null;
  at_baseline: boolean;
  /** True khi nội dung scene hiện tại trùng với bản gốc ban đầu (rev-001). */
  at_root?: boolean;
  /** ID mẫu trong thư viện mẫu đã được xuất từ job này; null/vắng = chưa xuất (API cũ không gửi). */
  published_sample_id?: string | null;
}

export interface DemoPublishResult {
  sample_id: string;
  title: string;
}

/** Kiểm trạng thái bản demo ở biên API: thiếu field là lỗi, không đoán. */
export function parseDemoState(value: unknown): DemoState {
  const invalid = () => new Error("Trạng thái bản demo không hợp lệ");
  if (!isRecord(value) || typeof value.job_id !== "string" || typeof value.at_baseline !== "boolean") throw invalid();
  if (!(value.current_revision === null || typeof value.current_revision === "string")) throw invalid();
  const baseline = value.baseline;
  if (baseline !== null && !(isRecord(baseline) && typeof baseline.scene_revision === "string" && typeof baseline.job_id === "string")) throw invalid();
  if (value.at_root !== undefined && typeof value.at_root !== "boolean") throw invalid();
  if (value.published_sample_id !== undefined && !(value.published_sample_id === null || typeof value.published_sample_id === "string")) throw invalid();
  return value as unknown as DemoState;
}

export function parseDemoPublishResult(value: unknown): DemoPublishResult {
  if (!isRecord(value) || typeof value.sample_id !== "string" || typeof value.title !== "string") {
    throw new Error("Kết quả xuất bản demo không hợp lệ");
  }
  return value as unknown as DemoPublishResult;
}

export interface SceneSummary {
  project: StudioProject;
  latest_job: JobManifest | null;
  preview_ready: boolean;
  /** Job mới nhất đang chờ người upload xem bản đã che mặt; API cũ không gửi trường này. */
  awaiting_anonymization_review?: boolean;
  /** Job xong nhưng tách theo vật lỗi hết số lần thử, chờ người dùng chọn; API cũ không gửi trường này. */
  awaiting_object_choice?: boolean;
  /** Bước "Duyệt vật & Tạo mesh": chờ duyệt, đang dựng, Tạo mesh lỗi; null = không còn việc hoặc scene cũ. API cũ không gửi. */
  geometry_review?: "waiting" | "running" | "failed" | null;
  /** Caller-specific ownership decision; absent on older APIs is treated as denied. */
  capabilities?: { can_delete_project: boolean };
  /** Thời gian máy đã xử lý (tổng các bước đã chạy xong), không gồm lúc xếp hàng và lúc chờ người dùng; null = chưa đo. */
  processing_seconds?: number | null;
  /** Người bấm chạy job mới nhất (tạo scene hoặc thử lại). */
  requested_by?: Actor | null;
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
  details?: Record<string, unknown> | null;
}

export interface StageProgress {
  note?: string | null;
  stage_id: StageId;
  state: StageState;
  started_at: string | null;
  completed_at: string | null;
  error: ExecutionErrorView | null;
}

export type ResourceName = "vram" | "ram" | "disk";
/** busy: job khác đang dùng; external: chương trình khác chiếm; exceeds_machine: vượt tổng máy; unmeasured: không đo được. */
export type ResourceWaitReason = "busy" | "external" | "exceeds_machine" | "unmeasured";

/** Lần đo gần nhất của worker khi job chờ tài nguyên (bind đúng revision của job). */
export interface ResourceWaitView {
  job_manifest_checksum: string;
  checked_at: string;
  required_gb: Record<ResourceName, number>;
  available_gb: Record<ResourceName, number | null>;
  waiting_on: ResourceName[];
  /** measured: số "cần" lấy từ số đo các lượt chạy trước; configured_preview: ước lượng theo cấu hình. */
  estimate_scope: "configured_preview" | "measured";
  /** Chưa có số đo cho cấu hình này: job phải chạy một mình trên GPU. */
  needs_exclusive_gpu?: boolean;
  /** Thiếu ở observation do bản worker cũ ghi. */
  reasons?: Partial<Record<ResourceName, ResourceWaitReason>>;
  capacity_gb?: Partial<Record<ResourceName, number | null>>;
}

/** Vị trí của job theo đúng thứ tự worker sẽ nhận (xoay vòng theo người yêu cầu). Khớp `QueuePosition`. */
export interface QueuePositionView {
  /** 1 = job kế tiếp được nhận. */
  position: number;
  waiting: number;
  running: number;
  workers: number;
  /** Ước tính từ thời lượng đã đo của các lượt chạy trước; null khi chưa có số đo. */
  estimated_wait_seconds: number | null;
  estimate_samples: number;
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
  waiting_for?: "metric_confirmation" | "resources" | "anonymization_review" | "runtime" | null;
  resource_wait?: ResourceWaitView | null;
  /** Vị trí trong hàng đợi khi job đang chờ máy xử lý; null khi đang chạy, đã xong hoặc chờ người dùng. */
  queue?: QueuePositionView | null;
  error: ExecutionErrorView | null;
  /** Per-job permissions supplied by the server; quota remains a separate policy. */
  capabilities?: { can_mutate: boolean; can_cancel: boolean; can_retry: boolean };
}

/** Nguồn số đo: người dùng đo ngoài đời, hoặc LiDAR của dataset mẫu (ADR 0004 §6). */
/** `ai_estimated`: khoảng cách lấy từ đề xuất tự động (ADR 0001 §2), không phải số đo ngoài đời. */
/** `lidar_trajectory`: khoảng cách suy từ gói LiDAR của job qua căn chỉnh quỹ đạo (ADR 0009), không ai chọn điểm. */
export type DistanceSource = "user_measured" | "lidar_demo" | "ai_estimated" | "lidar_trajectory";

/**
 * Đề xuất tỉ lệ mét và mặt sàn tự động của worker (MoGe-2 + điểm thưa COLMAP). Luôn là ước lượng:
 * người dùng chấp nhận hoặc sửa ở bước xác nhận. Khớp `MetricProposal` backend.
 */
/** Bằng chứng căn chỉnh của đề xuất lấy từ gói LiDAR: pose camera cuối cùng so với quỹ đạo người dùng nộp. */
export interface TrajectoryAlignment {
  trajectory_origin: "estimated" | "ground_truth";
  input_frames: number;
  registered_frames: number;
  offset_median_m: number;
  offset_p90_m: number;
  offset_max_m: number;
  path_length_m: number;
}

export interface MetricProposal {
  status: "ESTIMATED";
  job_id: string;
  /** `lidar_trajectory_alignment`: tỉ lệ và sàn lấy từ gói LiDAR; mặc định là ước lượng của mô hình đoán độ sâu. */
  method?: "moge2_sparse_depth_scale_only" | "lidar_trajectory_alignment";
  alignment?: TrajectoryAlignment | null;
  scale_m_per_sfm_unit: number;
  /** Độ phân tán tương đối của tỉ lệ giữa các ảnh. */
  frame_dispersion: number;
  /** Sai số chuẩn tương đối của tỉ lệ (chỉ phần nhiễu giữa các ảnh). */
  relative_uncertainty: number;
  frames_used: number;
  pairs_used: number;
  floor: { points: [MetricPoint, MetricPoint, MetricPoint]; residual_m: number; support_points: number } | null;
  segments: {
    point_a: MetricPoint; point_b: MetricPoint; distance_m: number;
    check_a: MetricPoint; check_b: MetricPoint; check_distance_m: number;
  } | null;
}

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

export interface DemoFact {
  label: string;
  value: string;
}

/** Một thẻ kết quả của bước; thêm kiểu mới ở đây và ở `showcase/registry.tsx`. */
export interface DemoStageAsset {
  kind: "image" | "video" | "facts";
  title?: string;
  caption?: string;
  file?: DemoFile | null;
  facts?: DemoFact[];
}

export interface DemoStage {
  stage_id: StageId;
  /** Bundle cũ chỉ liệt kê stage đã chạy; API mới thêm pending cho các bước thiếu. */
  state?: "succeeded" | "pending" | "failed";
  duration_seconds: number | null;
  summary: string;
  /** Kết quả hiển thị của bước (ảnh, video, số đo thật); bundle cũ không có. */
  assets?: DemoStageAsset[];
}

export type ParamValue = number | string;

export interface ParameterSpec {
  key: string;
  group: "sampling" | "colmap" | "brush" | "geometry" | "scene" | "simulation";
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
  headroom_measured?: boolean;
  vram_free_gb?: number | null;
  ram_available_gb?: number | null;
  gpu_uuid?: string | null;
  disk_total_gb?: number | null;
  /** Mốc "máy rảnh": lần đo gần nhất khi pipeline không dùng máy; preset Maximum tính theo mốc này. */
  idle_measured_at?: string | null;
  idle_vram_free_gb?: number | null;
  idle_ram_available_gb?: number | null;
  idle_disk_free_gb?: number | null;
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
  presets: Record<string, Record<string, ParamValue>>;
  capability: MachineCapability | null;
  default_evaluation: ProcessingEvaluation;
  resource_note: string;
  /** Deployment có bộ che khuôn mặt/biển số: mới hiện lựa chọn tự động che. Server cũ không gửi trường này. */
  anonymize_available?: boolean;
  /** Deployment bắt buộc che cho mọi job: lựa chọn hiện ở trạng thái bật và không tắt được. */
  anonymize_enforced?: boolean;
}

export interface ScenarioPreferences {
  input_type: "video_continuous" | "video_loop_360" | "photo_set";
  environment: "indoor" | "outdoor";
  subject_scope: "single_object" | "full_room";
  target_capacity: "minimum_quality" | "balanced" | "machine_maximum";
}

export interface SuggestResponse {
  preset_name: string;
  params: Record<string, ParamValue>;
  evaluation: ProcessingEvaluation;
}

/** Reject malformed suggestions before applying them to the configuration form. */
export function parseSuggestResponse(value: unknown): SuggestResponse {
  const validStatus = (status: unknown) => ["ok", "warn", "danger", "unknown"].includes(String(status));
  if (!isRecord(value) || typeof value.preset_name !== "string" || !value.preset_name.trim() ||
      !isRecord(value.params) || Object.keys(value.params).length === 0 ||
      !Object.values(value.params).every((item) => typeof item === "string" || isFiniteNumber(item))) {
    throw new Error("Gợi ý cấu hình từ backend không hợp lệ");
  }
  const evaluation = value.evaluation;
  if (!isRecord(evaluation) || typeof evaluation.blocking !== "boolean" || typeof evaluation.note !== "string" ||
      !Array.isArray(evaluation.resources) || evaluation.resources.length !== 3 ||
      !Array.isArray(evaluation.parameters) || evaluation.parameters.length === 0) {
    throw new Error("Đánh giá tài nguyên của gợi ý không hợp lệ");
  }
  const resources = new Set<string>();
  for (const item of evaluation.resources) {
    if (!isRecord(item) || !["vram", "ram", "disk"].includes(String(item.resource)) ||
        !isFiniteNumber(item.required_gb) || item.required_gb < 0 ||
        !(item.available_gb === null || (isFiniteNumber(item.available_gb) && item.available_gb >= 0)) ||
        !validStatus(item.status) || typeof item.message !== "string") {
      throw new Error("Số liệu tài nguyên của gợi ý không hợp lệ");
    }
    resources.add(String(item.resource));
  }
  if (resources.size !== 3 || !evaluation.parameters.every((item) =>
    isRecord(item) && typeof item.key === "string" && Object.hasOwn(value.params as object, item.key) &&
    validStatus(item.status) && (item.message === null || typeof item.message === "string")
  )) throw new Error("Thông số đánh giá của gợi ý không hợp lệ");
  return value as unknown as SuggestResponse;
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

export interface DemoObjectGeometry {
  state: "succeeded" | "pending" | "failed";
  duration_seconds: number | null;
  objectgs_count: number | null;
  shell_count: number | null;
  collider_count: number | null;
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
  object_geometry?: DemoObjectGeometry | null;
  video: DemoFile | null;
  video_caption?: string | null;
  frames: DemoFile[];
  frame_count: number | null;
  splat: DemoFile;
  processing?: Record<string, ParamValue> | null;
  machine?: Record<string, string>;
  cameras?: { frame_id: number; center: [number, number, number]; rotation_xyzw: [number, number, number, number] }[];
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
        !STAGE_STATES.includes(stage.state as StageState) ||
        (stage.note !== undefined && stage.note !== null && typeof stage.note !== "string")) {
      throw new Error("Stage trong tiến trình không hợp lệ");
    }
  }
  if (value.waiting_for !== undefined && value.waiting_for !== null && value.waiting_for !== "metric_confirmation" && value.waiting_for !== "resources" && value.waiting_for !== "anonymization_review" && value.waiting_for !== "runtime") {
    throw new Error("Lý do chờ của job không hợp lệ");
  }
  if (value.resource_wait !== undefined && value.resource_wait !== null) {
    const wait = value.resource_wait;
    if (!isRecord(wait) || typeof wait.checked_at !== "string" || typeof wait.job_manifest_checksum !== "string" ||
        !isRecord(wait.required_gb) || !isRecord(wait.available_gb) || !Array.isArray(wait.waiting_on) ||
        (wait.estimate_scope !== "configured_preview" && wait.estimate_scope !== "measured") ||
        (wait.needs_exclusive_gpu !== undefined && typeof wait.needs_exclusive_gpu !== "boolean") ||
        !["vram", "ram", "disk"].every((key) => isFiniteNumber((wait.required_gb as Record<string, unknown>)[key]) &&
          ((wait.available_gb as Record<string, unknown>)[key] === null || isFiniteNumber((wait.available_gb as Record<string, unknown>)[key]))) ||
        !wait.waiting_on.every((key) => typeof key === "string" && ["vram", "ram", "disk"].includes(key))) {
      throw new Error("Snapshot tài nguyên chờ không hợp lệ");
    }
    const reasons = wait.reasons ?? {};
    const capacity = wait.capacity_gb ?? {};
    if (!isRecord(reasons) || !isRecord(capacity) ||
        !Object.entries(reasons).every(([key, reason]) => ["vram", "ram", "disk"].includes(key) &&
          ["busy", "external", "exceeds_machine", "unmeasured"].includes(String(reason))) ||
        !Object.entries(capacity).every(([key, amount]) => ["vram", "ram", "disk"].includes(key) &&
          (amount === null || isFiniteNumber(amount)))) {
      throw new Error("Lý do chờ tài nguyên không hợp lệ");
    }
  }
  if (value.queue !== undefined && value.queue !== null) {
    const queue = value.queue;
    if (!isRecord(queue) || !["position", "waiting", "running", "workers", "estimate_samples"].every((key) => Number.isInteger(queue[key]) && (queue[key] as number) >= 0) ||
        (queue.position as number) < 1 || (queue.workers as number) < 1 ||
        (queue.estimated_wait_seconds !== null && !(isFiniteNumber(queue.estimated_wait_seconds) && queue.estimated_wait_seconds >= 0))) {
      throw new Error("Vị trí hàng đợi từ backend không hợp lệ");
    }
  }
  if (value.capabilities !== undefined && value.capabilities !== null) {
    const capabilities = value.capabilities;
    if (!isRecord(capabilities) || !["can_mutate", "can_cancel", "can_retry"].every((key) => typeof capabilities[key] === "boolean")) {
      throw new Error("Quyền thao tác job từ backend không hợp lệ");
    }
  }
  return value as unknown as JobProgress;
}

/** Loại thẻ frontend biết vẽ; loại lạ (backend mới hơn) bị bỏ qua từng thẻ chứ không làm hỏng cả mẫu. */
const ASSET_KINDS = ["image", "video", "facts"];

function isDemoAsset(asset: unknown): boolean {
  if (!isRecord(asset) || !ASSET_KINDS.includes(String(asset.kind))) return false;
  if (asset.kind === "facts") {
    return Array.isArray(asset.facts) && asset.facts.length > 0 && !asset.file &&
      asset.facts.every((fact) => isRecord(fact) && typeof fact.label === "string" && typeof fact.value === "string");
  }
  return isRecord(asset.file) && typeof asset.file.name === "string" && SAFE_NAME.test(asset.file.name);
}

/** Tên file demo phải phẳng (không path) vì được ghép vào URL. */
export function parseDemoManifest(value: unknown): DemoManifest {
  if (!isRecord(value) || value.schema_version !== "1.0" || !isRecord(value.splat) ||
      !Array.isArray(value.frames) || !Array.isArray(value.stages) ||
      (value.origin !== "pipeline_job" && value.origin !== "smoke_run")) {
    throw new Error("Demo bundle không hợp lệ");
  }
  for (const stage of value.stages) {
    if (isRecord(stage) && Array.isArray(stage.assets)) {
      stage.assets = stage.assets.filter((asset) => isRecord(asset) && ASSET_KINDS.includes(String(asset.kind)));
    }
  }
  const geometry = value.object_geometry;
  if (geometry !== undefined && geometry !== null) {
    if (!isRecord(geometry) || !["succeeded", "pending", "failed"].includes(String(geometry.state)) ||
        (geometry.duration_seconds !== null && (!isFiniteNumber(geometry.duration_seconds) || geometry.duration_seconds <= 0)) ||
        !["objectgs_count", "shell_count", "collider_count"].every((key) => geometry[key] === null ||
          (isFiniteNumber(geometry[key]) && Number.isInteger(geometry[key]) && geometry[key] >= 0))) {
      throw new Error("Kết quả tạo mesh của mẫu không hợp lệ");
    }
  }
  const assetFiles = value.stages.flatMap((stage) =>
    isRecord(stage) && Array.isArray(stage.assets) ? stage.assets.flatMap((asset) => (isRecord(asset) && asset.file ? [asset.file] : [])) : []);
  const files = [value.splat, ...(value.video ? [value.video] : []), ...value.frames, ...assetFiles];
  if (!files.every((file) => isRecord(file) && typeof file.name === "string" && SAFE_NAME.test(file.name))) {
    throw new Error("Tên file demo không hợp lệ");
  }
  const ids = new Set<string>();
  for (const stage of value.stages) {
    if (!isRecord(stage) || typeof stage.stage_id !== "string" || ids.has(stage.stage_id) ||
        (stage.state !== undefined && !["succeeded", "pending", "failed"].includes(String(stage.state))) ||
        (stage.duration_seconds !== null && (!isFiniteNumber(stage.duration_seconds) || stage.duration_seconds < 0))) {
      throw new Error("Stage demo từ backend không hợp lệ");
    }
    ids.add(stage.stage_id);
    if (stage.assets !== undefined && !(Array.isArray(stage.assets) && stage.assets.every(isDemoAsset))) {
      throw new Error("Thẻ kết quả của bước demo không hợp lệ");
    }
  }
  if (value.cameras !== undefined && value.cameras !== null) {
    if (!Array.isArray(value.cameras) || !value.cameras.every((camera) => isRecord(camera) && Array.isArray(camera.center) && camera.center.every(isFiniteNumber))) {
      throw new Error("Dữ liệu camera demo không hợp lệ");
    }
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
      !["user_measured", "lidar_demo", "ai_estimated", "lidar_trajectory"].includes(String(value.distance_source)) ||
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

function isMetricPoint(value: unknown): value is MetricPoint {
  return Array.isArray(value) && value.length === 3 && value.every(isFiniteNumber);
}

/** Đề xuất tự động phải có tỉ lệ dương, hữu hạn và điểm hợp lệ trước khi điền vào bước xác nhận. */
export function parseMetricProposal(value: unknown): MetricProposal {
  const positive = (item: unknown) => isFiniteNumber(item) && item > 0;
  const floor = isRecord(value) ? value.floor : undefined;
  const pairs = isRecord(value) ? value.segments : undefined;
  if (!isRecord(value) || value.status !== "ESTIMATED" || typeof value.job_id !== "string" ||
      !positive(value.scale_m_per_sfm_unit) || !isFiniteNumber(value.frame_dispersion) || value.frame_dispersion < 0 ||
      !isFiniteNumber(value.relative_uncertainty) || value.relative_uncertainty < 0 ||
      !positive(value.frames_used) || !positive(value.pairs_used) ||
      (floor !== null && !(isRecord(floor) && Array.isArray(floor.points) && floor.points.length === 3 &&
        floor.points.every(isMetricPoint) && isFiniteNumber(floor.residual_m))) ||
      (pairs !== null && !(isRecord(pairs) && [pairs.point_a, pairs.point_b, pairs.check_a, pairs.check_b].every(isMetricPoint) &&
        positive(pairs.distance_m) && positive(pairs.check_distance_m)))) {
    throw new Error("Đề xuất tỉ lệ tự động từ backend không hợp lệ");
  }
  return value as unknown as MetricProposal;
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
  /** Source→display Y-up, chỉ hướng hiển thị; không đổi đơn vị hoặc artifact. */
  display_rotation_xyzw?: [number, number, number, number] | null;
  refs: { artifact_uri: string; artifact_checksum: string; artifact_type: string }[];
  cameras: { frame_id: number; center: [number, number, number]; rotation_xyzw: [number, number, number, number] }[];
  /** Khoá của lớp LiDAR đã căn chỉnh chồng lên scene; null/thiếu = scene không có lớp này. */
  lidar_overlay?: string | null;
}

const VIEW_KINDS: readonly StageView["kind"][] = ["frames", "cameras", "gaussian", "mesh"];

/** Danh sách lớp xem: kind phải biết, ref phải có URI/checksum, camera phải hữu hạn. */
export function parseStageViews(value: unknown): StageView[] {
  if (!isRecord(value) || !Array.isArray(value.views)) throw new Error("Danh sách kết quả từng bước không hợp lệ");
  for (const view of value.views) {
    const rotation = isRecord(view) ? view.display_rotation_xyzw : undefined;
    if (rotation != null && !(Array.isArray(rotation) && rotation.length === 4 &&
        rotation.every(isFiniteNumber) && Math.abs(Math.hypot(...rotation) - 1) < 1e-6)) {
      throw new Error("Hướng hiển thị của lớp xem không hợp lệ");
    }
    if (!isRecord(view) || !VIEW_KINDS.includes(view.kind as StageView["kind"]) || typeof view.title !== "string" ||
        !Array.isArray(view.refs) || !Array.isArray(view.cameras) ||
        !view.refs.every((ref) => isRecord(ref) && typeof ref.artifact_uri === "string" && typeof ref.artifact_checksum === "string") ||
        !view.cameras.every((camera) => isRecord(camera) && Array.isArray(camera.center) && camera.center.every(isFiniteNumber)) ||
        !(view.lidar_overlay === undefined || view.lidar_overlay === null || typeof view.lidar_overlay === "string")) {
      throw new Error("Một lớp xem không hợp lệ");
    }
  }
  return value.views as unknown as StageView[];
}

/** Một cột của màn hình so sánh 3 hướng tỉ lệ (ADR 0004 §5). Khớp `ModeResult`. */
export interface ModeResult {
  mode: "rgb_only" | "user_anchor" | "lidar";
  title: string;
  status: "mock" | "estimated" | "confirmed" | "measured" | "missing";
  note: string;
  steps: string[];
  scale_m_per_sfm_unit: number | null;
  relative_uncertainty?: number | null;
  frames_used?: number | null;
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

/** Chỉ trạng thái có kết quả thật mới được mang tỉ lệ; `mock` còn nhận từ API cũ. */
export function parseModeComparison(value: unknown): ModeComparison {
  if (!isRecord(value) || !Array.isArray(value.modes) || value.modes.length !== 3) {
    throw new Error("So sánh 3 hướng từ backend không hợp lệ");
  }
  for (const mode of value.modes) {
    if (!isRecord(mode) || typeof mode.title !== "string" || !["mock", "estimated", "confirmed", "measured", "missing"].includes(String(mode.status))) {
      throw new Error("Một hướng so sánh không hợp lệ");
    }
    const available = ["estimated", "confirmed", "measured"].includes(String(mode.status));
    if (!available && mode.scale_m_per_sfm_unit != null) throw new Error("Hướng chưa có kết quả không được có số tỉ lệ");
    if (available && (!isFiniteNumber(mode.scale_m_per_sfm_unit) || mode.scale_m_per_sfm_unit <= 0)) throw new Error("Thiếu tỉ lệ hợp lệ");
    if (mode.relative_uncertainty != null && (!isFiniteNumber(mode.relative_uncertainty) || mode.relative_uncertainty < 0)) throw new Error("Độ bất định không hợp lệ");
    if (mode.frames_used != null && (!Number.isInteger(mode.frames_used) || Number(mode.frames_used) < 1)) throw new Error("Số ảnh không hợp lệ");
  }
  return value as unknown as ModeComparison;
}

/** Scene import từ file 3DGS, chỉ xem/chỉnh sửa (ADR 0004 §3). Khớp `ImportedScene`. */
export interface ImportedScene {
  import_id: string;
  upload_id: string;
  name: string;
  input_kind: "gaussian_ply" | "gaussian_ply_colmap" | "gaussian_sog";
  status: "PACKAGING" | "READY" | "FAILED" | "CANCELLED";
  operation?: {
    operation_id: string;
    status: "QUEUED" | "WAITING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
    attempt: number;
    attempt_history?: {
      attempt: number;
      status: "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "INTERRUPTED";
      started_at: string;
      finished_at?: string | null;
      failure_code?:
        | "invalid_source"
        | "source_unavailable"
        | "runtime_failure"
        | "publication_failure"
        | "packaging_failure"
        | "resource_conflict"
        | "resource_wait"
        | "worker_interrupted"
        | null;
      retryable?: boolean | null;
      error?: string | null;
    }[];
    error: string | null;
    failure_code?:
      | "invalid_source"
      | "source_unavailable"
      | "runtime_failure"
      | "publication_failure"
      | "packaging_failure"
      | "resource_conflict"
      | "resource_wait"
      | "worker_interrupted"
      | null;
    retryable?: boolean | null;
    cancel_requested?: boolean;
    cancel_requested_at?: string | null;
    created_at: string;
    updated_at: string;
  } | null;
  delivery_ref: { artifact_uri: string; artifact_checksum: string } | null;
  initial_camera?: {
    position: [number, number, number];
    target: [number, number, number];
    fov?: number;
  } | null;
  default_camera?: {
    position: [number, number, number];
    target: [number, number, number];
    fov?: number;
  } | null;
  error: string | null;
  created_at: string;
  created_by_name?: string | null;
  created_by_role?: "guest" | "editor" | "reviewer" | null;
  /** Missing capability data from an older API falls back to role; Guests fail closed. */
  capabilities?: { can_delete: boolean; can_retry?: boolean; can_cancel?: boolean };
}
