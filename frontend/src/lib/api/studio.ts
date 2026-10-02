/**
 * Endpoint Studio MVP. Đi qua cùng biên `fetchApi` của Web Studio; riêng upload
 * dùng XMLHttpRequest vì `fetch` chưa báo được tiến độ gửi body.
 */

import { ApiError, apiFetch, apiUrl, fetchApi, type ApiResult } from "@/lib/api/client";
import { directUpload, xhrPutPart } from "@/lib/api/directUpload";
import type { SceneEditResponse, SceneResponse } from "@/lib/contracts/api";
import {
  parseDemoManifest,
  parseDemoSelection,
  parseMetricProposal,
  parseJobProgress,
  parseLidarMeasurements,
  parseMetricPreview,
  parseModeComparison,
  parseStageViews,
  type DemoManifest,
  type DemoSelection,
  type MetricProposal,
  type ImportedScene,
  type JobProgress,
  type LidarAttachment,
  type LidarMeasurements,
  type MetricInput,
  type MetricPoint,
  type MetricPreview,
  type ModeComparison,
  type ParamValue,
  type ProcessingEvaluation,
  type ProcessingOptions,
  type SampleSummary,
  type SceneFromUpload,
  type SceneSummary,
  type SourceRightsAttestation,
  type StageView,
  type UploadRecord,
} from "@/lib/contracts/studio";

/** Kết quả xem được của từng bước (frame, camera, 3DGS, collision mesh). */
export async function getStageViews(jobId: string, signal?: AbortSignal): Promise<StageView[]> {
  const data = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/stage-views`, { signal });
  return parseStageViews(data);
}

const API = "/api/v1";

export function listScenes(): Promise<ApiResult<{ scenes: SceneSummary[] }>> {
  return fetchApi<{ scenes: SceneSummary[] }>(`${API}/scenes`);
}

export function listUploads(): Promise<ApiResult<{ uploads: UploadRecord[] }>> {
  return fetchApi<{ uploads: UploadRecord[] }>(`${API}/uploads`);
}

export function createSceneFromUpload(
  uploadId: string,
  name: string,
  attestation: SourceRightsAttestation,
  processing?: Record<string, ParamValue>,
  lidar?: LidarAttachment,
): Promise<SceneFromUpload> {
  return apiFetch<SceneFromUpload>(`${API}/scenes/from-upload`, {
    method: "POST",
    body: JSON.stringify({ upload_id: uploadId, name, attestation, processing, lidar }),
  });
}

/** Thông số chỉnh được, preset và cấu hình máy worker (từ file cấu hình chung). */
export function getProcessingOptions(): Promise<ApiResult<ProcessingOptions>> {
  return fetchApi<ProcessingOptions>(`${API}/processing/options`);
}

/** Ước lượng tài nguyên của bộ thông số so với máy worker. */
export function evaluateProcessing(
  params: Record<string, ParamValue>,
  signal?: AbortSignal,
): Promise<ApiResult<ProcessingEvaluation>> {
  return fetchApi<ProcessingEvaluation>(`${API}/processing/evaluate`, {
    method: "POST",
    body: JSON.stringify({ params }),
    signal,
  });
}

export async function getJobProgress(jobId: string, signal?: AbortSignal): Promise<ApiResult<JobProgress>> {
  const result = await fetchApi<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/progress`, { signal });
  if (!result.ok) return result;
  try {
    return { ok: true, data: parseJobProgress(result.data) };
  } catch (cause) {
    return { ok: false, error: new ApiError(502, cause instanceof Error ? cause.message : "Tiến trình không hợp lệ") };
  }
}

export function cancelJob(jobId: string): Promise<unknown> {
  return apiFetch(`${API}/jobs/${encodeURIComponent(jobId)}/transitions`, {
    method: "POST",
    body: JSON.stringify({ target_status: "CANCELLED" }),
  });
}

export function retryJob(jobId: string): Promise<unknown> {
  return apiFetch(`${API}/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
}

/** Video mẫu đã xử lý sẵn (thẻ ở bước tải video lên). */
export function listSamples(): Promise<ApiResult<{ samples: SampleSummary[] }>> {
  return fetchApi<{ samples: SampleSummary[] }>(`${API}/samples`);
}

/** Manifest đầy đủ của một video mẫu, parse tại biên. */
export async function getSample(sampleId: string): Promise<ApiResult<DemoManifest>> {
  const result = await fetchApi<unknown>(`${API}/samples/${encodeURIComponent(sampleId)}`);
  if (!result.ok) return result;
  try {
    return { ok: true, data: parseDemoManifest(result.data) };
  } catch (cause) {
    return { ok: false, error: new ApiError(502, cause instanceof Error ? cause.message : "Video mẫu không hợp lệ") };
  }
}

/** URL tương đối cùng origin để `<img>`, `<video>` và editor nhúng dùng được. */
export function sampleFileUrl(sampleId: string, name: string): string {
  return `${API}/samples/${encodeURIComponent(sampleId)}/files/${encodeURIComponent(name)}`;
}

export interface UploadHandle {
  promise: Promise<UploadRecord>;
  abort: () => void;
}

/**
 * Tải video lên: có kho file (ADR 0003) thì upload thẳng theo từng phần, không thì
 * stream qua API. `onProgress` nhận tỉ lệ bytes đã gửi (đo thật, 0..1); `onVerifying`
 * báo lúc server đang tự kiểm checksum sau khi gửi xong.
 */
export function uploadVideo(
  file: File,
  onProgress: (fraction: number) => void,
  onVerifying?: () => void,
): UploadHandle {
  const controller = new AbortController();
  let proxy: UploadHandle | null = null;
  const promise = (async () => {
    const config = await apiFetch<{ direct: boolean; max_bytes: number }>(`${API}/uploads/config`);
    if (file.size > config.max_bytes) {
      throw new ApiError(413, `Video vượt giới hạn ${formatLimit(config.max_bytes)}`);
    }
    if (!config.direct) {
      proxy = proxyUpload(file, onProgress);
      if (controller.signal.aborted) proxy.abort();
      return proxy.promise;
    }
    const state = await directUpload(
      file,
      { onProgress, onVerifying, signal: controller.signal },
      { api: apiFetch, putPart: xhrPutPart, sleep: (ms) => new Promise((r) => setTimeout(r, ms)), storage: browserStorage() },
    );
    const uploads = await apiFetch<{ uploads: UploadRecord[] }>(`${API}/uploads`);
    const record = uploads.uploads.find((item) => item.upload_id === state.upload_id);
    if (!record) throw new ApiError(404, "Không thấy video vừa tải lên trong danh sách");
    return record;
  })();
  return {
    promise,
    abort: () => {
      controller.abort();
      proxy?.abort();
    },
  };
}

function browserStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function formatLimit(bytes: number): string {
  return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`;
}

/** Đường cũ: stream cả file qua API (`/uploads`) khi deployment chưa có kho file. */
function proxyUpload(file: File, onProgress: (fraction: number) => void): UploadHandle {
  const request = new XMLHttpRequest();
  const promise = new Promise<UploadRecord>((resolve, reject) => {
    request.open("POST", `${API}/uploads?filename=${encodeURIComponent(file.name)}`);
    request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(JSON.parse(request.responseText) as UploadRecord);
        return;
      }
      let detail = request.responseText || `HTTP ${request.status}`;
      try {
        const parsed = JSON.parse(request.responseText) as { detail?: unknown };
        if (typeof parsed.detail === "string") detail = parsed.detail;
      } catch {
        // Body không phải JSON: giữ text thô.
      }
      reject(new ApiError(request.status, detail));
    };
    request.onerror = () => reject(new ApiError(0, "Mất kết nối khi đang tải video lên"));
    request.onabort = () => reject(new ApiError(499, "Đã hủy tải lên"));
    request.send(file);
  });
  return { promise, abort: () => request.abort() };
}

/** Scene có số đo LiDAR sẵn (dataset mẫu) không; lỗi mạng coi như không có (nhập tay). */
export async function getMetricAssist(jobId: string): Promise<{ lidar_available: boolean }> {
  const result = await fetchApi<{ lidar_available: boolean }>(`${API}/jobs/${encodeURIComponent(jobId)}/metric/assist`);
  return result.ok && typeof result.data.lidar_available === "boolean" ? result.data : { lidar_available: false };
}

/** Đo A/B và C/D trên LiDAR để điền sẵn khoảng cách (chỉ scene có hỗ trợ LiDAR). */
export async function measureOnLidar(
  jobId: string,
  anchor: [MetricPoint, MetricPoint],
  check: [MetricPoint, MetricPoint],
  signal?: AbortSignal,
): Promise<LidarMeasurements> {
  const data = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/metric/lidar`, {
    method: "POST",
    body: JSON.stringify({ point_a: anchor[0], point_b: anchor[1], check_a: check[0], check_b: check[1] }),
    signal,
  });
  return parseLidarMeasurements(data);
}

/** Dataset mẫu: hệ thống tự chọn 7 điểm trên sàn LiDAR và đo sẵn. */
export async function getDemoPoints(jobId: string): Promise<DemoSelection> {
  const data = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/metric/demo-points`);
  return parseDemoSelection(data);
}

/** Đề xuất tỉ lệ/mặt sàn tự động của scene; null khi worker không tạo (không bật hoặc không đủ dữ liệu). */
export async function getMetricProposal(jobId: string): Promise<MetricProposal | null> {
  const result = await fetchApi<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/metric/proposal`);
  if (!result.ok) return null;
  try {
    return parseMetricProposal(result.data);
  } catch {
    return null; // Đề xuất hỏng thì coi như không có: người dùng vẫn nhập tay được.
  }
}

/** Xem trước tỉ lệ mét từ điểm đã chọn; backend chưa ghi xác nhận. */
export async function previewMetric(jobId: string, input: MetricInput): Promise<MetricPreview> {
  const data = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/metric/preview`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  return parseMetricPreview(data);
}

/** Xác nhận đúng bản xem trước đã hiển thị (checksum); người xác nhận lấy từ phiên đăng nhập. */
export function confirmMetric(jobId: string, input: MetricInput, previewChecksum: string): Promise<unknown> {
  return apiFetch(`${API}/jobs/${encodeURIComponent(jobId)}/metric/confirm`, {
    method: "POST",
    body: JSON.stringify({ input, preview_checksum: previewChecksum }),
  });
}

/** Demo 3 hướng tỉ lệ trên cùng scene: RGB only (mô phỏng), anchor người dùng, LiDAR. */
export async function getModeComparison(jobId: string, signal?: AbortSignal): Promise<ModeComparison> {
  const data = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/metric/comparison`, { signal });
  return parseModeComparison(data);
}

/** Tạo scene import từ upload 3DGS; máy chủ nén PLY → SOG trong nền. */
export function createImport(uploadId: string, name: string): Promise<ImportedScene> {
  return apiFetch<ImportedScene>(`${API}/imports`, { method: "POST", body: JSON.stringify({ upload_id: uploadId, name }) });
}

export function getImport(importId: string, signal?: AbortSignal): Promise<ApiResult<ImportedScene>> {
  return fetchApi<ImportedScene>(`${API}/imports/${encodeURIComponent(importId)}`, { signal });
}

export function listImports(): Promise<ApiResult<{ imports: ImportedScene[] }>> {
  return fetchApi<{ imports: ImportedScene[] }>(`${API}/imports`);
}

/** URL SOG của scene import (tên file `.sog` để viewer chọn đúng parser). */
export function importContentUrl(importId: string): string {
  return `${API}/imports/${encodeURIComponent(importId)}/content/scene.sog`;
}

// ── vật thể trong SceneIR (PRODUCT-07/07A, ADR 0006) ─────────────────────────

/** SceneIR hiện tại của job; 404 khi bước tách vật thể chưa publish revision nào. */
export function getJobScene(jobId: string, signal?: AbortSignal): Promise<ApiResult<SceneResponse>> {
  return fetchApi<SceneResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene`, { signal });
}

export type ObjectAction = "confirm" | "ignore" | "hide" | "delete" | "rename" | "restore" | "duplicate" | "label";

/** Thao tác trên một vật thể; `expectedRevision` là khoá optimistic (revision cũ → 409). */
export function applyObjectAction(
  jobId: string,
  objectId: string,
  action: ObjectAction,
  expectedRevision: string,
  extra: { active?: boolean; name?: string; semantic_class?: string | null; mass_kg?: number | null; asset_family?: string | null } = {},
): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(
    `${API}/jobs/${encodeURIComponent(jobId)}/scene/objects/${encodeURIComponent(objectId)}/${action}`,
    { method: "POST", body: JSON.stringify({ expected_scene_revision: expectedRevision, ...extra }) },
  );
}

/** Thêm vật cản hộp; `center` là tâm hộp theo mét trong khung world (sàn z = 0). */
export function addBoxObstacle(
  jobId: string,
  expectedRevision: string,
  name: string,
  dimensions: [number, number, number],
  center: [number, number, number],
): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/objects`, {
    method: "POST",
    body: JSON.stringify({
      expected_scene_revision: expectedRevision,
      name,
      dimensions_xyz_m: dimensions,
      position_xyz: center,
    }),
  });
}

// ── scene theo vật (pipeline v2, ADR 0007) ───────────────────────────────────

/** Ghi transform mới của một vật (mét, Z-up) thành revision kế tiếp. */
export function setObjectTransform(
  jobId: string,
  expectedRevision: string,
  objectId: string,
  translation: [number, number, number],
  rotation: [number, number, number, number],
): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/edits`, {
    method: "POST",
    body: JSON.stringify({
      expected_scene_revision: expectedRevision,
      edits: [{ object_id: objectId, translation_xyz: translation, rotation_quaternion_xyzw: rotation }],
    }),
  });
}

export interface CatalogEntry {
  family: string;
  semantic_class: string | null;
  size_xyz_m: [number, number, number];
  dynamic: boolean;
  default_mass_kg: number | null;
  /** Máy chủ có GLB hình khối của asset; không có thì vẽ hộp. */
  has_preview?: boolean;
}

export interface SceneCatalog {
  classes: string[];
  entries: CatalogEntry[];
  physics_note: string;
}

/** GLB hình khối của một asset danh mục (mét, Z lên, tâm hộp bao tại gốc). */
export function catalogPreviewUrl(family: string): string {
  return apiUrl(`${API}/scene/catalog/${encodeURIComponent(family)}/preview.glb`, {});
}

/** Danh mục nhãn + asset Isaac đặt được; giá trị vật lý là mặc định tham khảo. */
export function getSceneCatalog(signal?: AbortSignal): Promise<SceneCatalog> {
  return apiFetch<SceneCatalog>(`${API}/scene/catalog`, { signal });
}

/** Nhãn gợi ý theo kích thước vật (chỉ để sắp danh sách chọn; người dùng xác nhận). */
export function getLabelSuggestions(jobId: string, objectId: string, signal?: AbortSignal): Promise<{ suggestions: string[] }> {
  return apiFetch<{ suggestions: string[] }>(
    `${API}/jobs/${encodeURIComponent(jobId)}/scene/objects/${encodeURIComponent(objectId)}/label-suggestions`,
    { signal },
  );
}

/** Thêm một vật từ danh mục; `position` là điểm đặt trên sàn (mét). */
export function addCatalogObject(
  jobId: string,
  expectedRevision: string,
  family: string,
  position: [number, number, number],
): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/catalog-objects`, {
    method: "POST",
    body: JSON.stringify({ expected_scene_revision: expectedRevision, family, position_xyz: position }),
  });
}

/** Hoàn tác: đưa nội dung một revision cũ thành revision kế tiếp. */
export function restoreSceneRevision(
  jobId: string,
  expectedRevision: string,
  targetRevision: string,
): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/restore`, {
    method: "POST",
    body: JSON.stringify({ expected_scene_revision: expectedRevision, target_revision: targetRevision }),
  });
}

// ── dựng lại tập vật: chạy lại tách theo vật / dùng hộp ứng viên ─────────────

export type ObjectifyMode = "objectify" | "boxes";

/** Trạng thái tách theo vật của scene + yêu cầu dựng lại gần nhất (worker thực hiện). */
export interface ObjectifyState {
  status: "idle" | "queued" | "running" | "done" | "failed";
  mode: ObjectifyMode | null;
  /** Tách theo vật lỗi hết số lần thử; scene chỉ có môi trường, chờ người dùng chọn. */
  awaiting_choice: boolean;
  object_centric: boolean;
  /** Máy xử lý có runtime tách theo vật. */
  available: boolean;
  note: string | null;
  base_revision: string | null;
  result_revision: string | null;
  error: string | null;
}

export function getObjectifyState(jobId: string, signal?: AbortSignal): Promise<ObjectifyState> {
  return apiFetch<ObjectifyState>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/objectify`, { signal });
}

/** Xếp hàng dựng lại tập vật trên đúng revision đang hiển thị. */
export function requestObjectify(jobId: string, expectedRevision: string, mode: ObjectifyMode): Promise<ObjectifyState> {
  return apiFetch<ObjectifyState>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/objectify`, {
    method: "POST",
    body: JSON.stringify({ expected_scene_revision: expectedRevision, mode }),
  });
}

// ── gói mô phỏng Isaac (EX-SIM SIM-02…05) ───────────────────────────────────

export interface PreflightRuleView {
  rule_id: string;
  result: "PASS" | "FAIL" | "WARN" | string;
  affected_object_ids: string[];
  remediation: string | null;
}

/** Tập con của `SimulationPackage` backend mà UI hiển thị; các field khác bỏ qua. */
export interface SimulationPackageView {
  scene_revision: string;
  source_scene_revision: string;
  created_at: string;
  confirmed_objects: number;
  environment_triangles: number;
  carved_triangles: number;
  preflight: { blocking_result: string; rules: PreflightRuleView[] };
  package_ref: { artifact_uri: string; artifact_checksum: string } | null;
}

function parseSimulationPackage(value: unknown): SimulationPackageView | null {
  if (value === null) return null;
  const data = value as Partial<SimulationPackageView>;
  if (
    typeof data.scene_revision !== "string" ||
    typeof data.confirmed_objects !== "number" ||
    !data.preflight ||
    !Array.isArray(data.preflight.rules)
  ) {
    throw new ApiError(502, "Backend trả gói mô phỏng sai contract");
  }
  return data as SimulationPackageView;
}

/** Gói của revision scene hiện tại; null khi chưa tạo hoặc scene đã sửa sau lần tạo. */
export async function getSimulationPackage(jobId: string, signal?: AbortSignal): Promise<SimulationPackageView | null> {
  return parseSimulationPackage(
    await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/simulation-package`, { signal }),
  );
}

/** Tạo gói: preflight FAIL vẫn trả báo cáo (package_ref null), không đổi scene. */
export async function createSimulationPackage(jobId: string): Promise<SimulationPackageView> {
  const result = parseSimulationPackage(
    await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/simulation-package`, { method: "POST" }),
  );
  if (!result) throw new ApiError(502, "Backend không trả gói mô phỏng");
  return result;
}

// ── bản ghi Rerun của quá trình train 3DGS (chế độ xem tuỳ chọn, ngoài pipeline) ──

export interface TrainingRecording {
  available: boolean;
  size_bytes: number | null;
}

/** Job có bản ghi Rerun hay không; lỗi hoặc dữ liệu lạ coi như không có để chế độ xem chính không bị ảnh hưởng. */
export async function getTrainingRecording(jobId: string, signal?: AbortSignal): Promise<TrainingRecording> {
  const none: TrainingRecording = { available: false, size_bytes: null };
  try {
    const value = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/training-recording`, { signal });
    if (typeof value !== "object" || value === null) return none;
    const { available, size_bytes } = value as Record<string, unknown>;
    return { available: available === true, size_bytes: typeof size_bytes === "number" ? size_bytes : null };
  } catch {
    return none;
  }
}

export function trainingRecordingUrl(jobId: string): string {
  return `${API}/jobs/${encodeURIComponent(jobId)}/training-recording.rrd`;
}

export function simulationPackageDownloadUrl(jobId: string): string {
  return `${API}/jobs/${encodeURIComponent(jobId)}/simulation-package/download`;
}

// ── duyệt & phát hành (PRODUCT-10/11) ────────────────────────────────────────

export type RevisionStatus =
  | "DRAFT"
  | "PROCESSING"
  | "CANDIDATE_READY"
  | "VALIDATING"
  | "READY_FOR_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "RELEASED";

/** Tham chiếu tới một artifact làm bằng chứng (ảnh, log, replay…) của một check hoặc cặp Start–Goal. */
export interface EvidenceRefView {
  artifact_uri: string;
  artifact_checksum: string;
}

export interface ValidationCheckView {
  check_id: string;
  result: string;
  message: string | null;
  evidence_refs: EvidenceRefView[];
}

export interface PathResultView {
  pair_id: string;
  result: string;
  message: string | null;
  evidence_refs: EvidenceRefView[];
}

export interface ValidationReportView {
  overall_result: string;
  validator_version: string;
  candidate_checksum: string | null;
  report_checksum: string | null;
  environment_versions: Record<string, string>;
  checks: ValidationCheckView[];
  path_results: PathResultView[];
}

/** Phần `ReviewState` backend mà UI dùng, đã chuẩn hoá ở biên API (thiếu trường phụ thì nhận giá trị rỗng). */
export interface ReviewStateView {
  record: {
    scene_revision: string;
    status: RevisionStatus;
    candidate_checksum: string | null;
    validation_report_checksum: string | null;
  };
  validation: ValidationReportView | null;
  /** Báo cáo có bằng chứng chạy Isaac Sim thật không; null khi chưa có báo cáo hoặc backend không trả cờ. */
  isaac_runtime_proof: boolean | null;
  warning_ids: string[];
  approval: {
    reviewer_id: string;
    decision: "APPROVE" | "REJECT";
    reason: string | null;
    decided_at: string;
    candidate_checksum: string | null;
    validation_report_checksum: string | null;
    record_checksum: string | null;
    accepted_warning_ids: string[];
  } | null;
  release: {
    release_timestamp: string;
    release_manifest_checksum: string;
    candidate_checksum: string | null;
    validation_report_checksum: string | null;
  } | null;
  release_archive: { artifact_uri: string } | null;
  blockers: string[];
}

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function evidenceRefs(value: unknown): EvidenceRefView[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const uri = isObject(item) ? text(item.artifact_uri) : null;
    const checksum = isObject(item) ? text(item.artifact_checksum) : null;
    return uri && checksum ? [{ artifact_uri: uri, artifact_checksum: checksum }] : [];
  });
}

function validationReport(value: unknown): ValidationReportView | null {
  if (!isObject(value)) return null;
  const rows = (items: unknown, key: "check_id" | "pair_id") =>
    (Array.isArray(items) ? items : []).flatMap((item) => {
      const id = isObject(item) ? text(item[key]) : null;
      if (!isObject(item) || !id) return [];
      return [{ id, result: text(item.result) ?? "?", message: text(item.message), evidence_refs: evidenceRefs(item.evidence_refs) }];
    });
  const versions = isObject(value.environment_versions) ? value.environment_versions : {};
  return {
    overall_result: text(value.overall_result) ?? "?",
    validator_version: text(value.validator_version) ?? "?",
    candidate_checksum: text(value.candidate_checksum),
    report_checksum: text(value.report_checksum),
    environment_versions: Object.fromEntries(Object.entries(versions).flatMap(([key, version]) => (typeof version === "string" ? [[key, version]] : []))),
    checks: rows(value.checks, "check_id").map(({ id, ...rest }) => ({ check_id: id, ...rest })),
    path_results: rows(value.path_results, "pair_id").map(({ id, ...rest }) => ({ pair_id: id, ...rest })),
  };
}

function parseReviewState(value: unknown): ReviewStateView {
  const record = isObject(value) ? value.record : null;
  const status = isObject(record) ? text(record.status) : null;
  const revision = isObject(record) ? text(record.scene_revision) : null;
  if (!isObject(value) || !isObject(record) || !status || !revision || !Array.isArray(value.blockers)) {
    throw new ApiError(502, "Backend trả trạng thái duyệt sai contract");
  }
  const approval = isObject(value.approval) ? value.approval : null;
  const release = isObject(value.release) ? value.release : null;
  const archive = isObject(value.release_archive) ? text(value.release_archive.artifact_uri) : null;
  return {
    record: {
      scene_revision: revision,
      status: status as RevisionStatus,
      candidate_checksum: text(record.candidate_checksum),
      validation_report_checksum: text(record.validation_report_checksum),
    },
    validation: validationReport(value.validation),
    isaac_runtime_proof: typeof value.isaac_runtime_proof === "boolean" ? value.isaac_runtime_proof : null,
    warning_ids: strings(value.warning_ids),
    approval: approval && {
      reviewer_id: text(approval.reviewer_id) ?? "?",
      decision: approval.decision === "REJECT" ? "REJECT" : "APPROVE",
      reason: text(approval.reason),
      decided_at: text(approval.decided_at) ?? "",
      candidate_checksum: text(approval.candidate_checksum),
      validation_report_checksum: text(approval.validation_report_checksum),
      record_checksum: text(approval.record_checksum),
      accepted_warning_ids: strings(approval.accepted_warning_ids),
    },
    release: release && {
      release_timestamp: text(release.release_timestamp) ?? "",
      release_manifest_checksum: text(release.release_manifest_checksum) ?? "",
      candidate_checksum: text(release.candidate_checksum),
      validation_report_checksum: text(release.validation_report_checksum),
    },
    release_archive: archive ? { artifact_uri: archive } : null,
    blockers: strings(value.blockers),
  };
}

export async function getReviewState(jobId: string, signal?: AbortSignal): Promise<ReviewStateView> {
  return parseReviewState(await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/review-state`, { signal }));
}

/** Quyết định trên đúng gói + báo cáo đang hiển thị; backend lấy reviewer từ phiên đăng nhập. */
export async function submitReviewDecision(
  jobId: string,
  body: {
    decision: "APPROVE" | "REJECT";
    candidate_checksum: string;
    validation_report_checksum: string;
    accepted_warning_ids: string[];
    reason?: string;
  },
): Promise<ReviewStateView> {
  return parseReviewState(
    await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/review-decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
}

export async function retryReleaseSeal(jobId: string): Promise<ReviewStateView> {
  return parseReviewState(
    await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/release-seal`, { method: "POST" }),
  );
}

export function releaseDownloadUrl(jobId: string): string {
  return `${API}/jobs/${encodeURIComponent(jobId)}/release-download`;
}

/** Một thứ nằm trong mục thùng rác: scene, scene nhập, hoặc upload chỉ scene đó dùng. */
export interface TrashItem {
  kind: "scene" | "import" | "upload";
  identifier: string;
  name: string;
  detail: string;
}

/** Một mục thùng rác (STUDIO_UX_SPEC.md D-15). */
export interface TrashEntry {
  entry_id: string;
  title: string;
  deleted_at: string;
  /** Thời điểm mục tự bị xoá hẳn; null khi deployment tắt tự xoá. */
  expires_at: string | null;
  deleted_by: string | null;
  size_bytes: number;
  items: TrashItem[];
}

/** Kết quả theo từng mục: mục lỗi không chặn các mục còn lại. */
export interface TrashActionResult {
  done: string[];
  failed: { entry_id: string; reason: string }[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

const TRASH_KINDS = ["scene", "import", "upload"] as const;

/** Kiểm dữ liệu thùng rác ở biên API; dữ liệu sai dạng thành lỗi thay vì hiện sai. */
export function parseTrashEntries(data: unknown): TrashEntry[] {
  if (!isRecord(data) || !Array.isArray(data.entries)) throw new ApiError(502, "Dữ liệu thùng rác không hợp lệ");
  return data.entries.map((entry) => {
    if (
      !isRecord(entry) || typeof entry.entry_id !== "string" || typeof entry.title !== "string" ||
      typeof entry.deleted_at !== "string" || typeof entry.size_bytes !== "number" || !Array.isArray(entry.items)
    ) throw new ApiError(502, "Dữ liệu thùng rác không hợp lệ");
    const items = entry.items.map((item) => {
      const kind = isRecord(item) ? TRASH_KINDS.find((value) => value === item.kind) : undefined;
      if (!isRecord(item) || !kind || typeof item.identifier !== "string" || typeof item.name !== "string") {
        throw new ApiError(502, "Dữ liệu thùng rác không hợp lệ");
      }
      return { kind, identifier: item.identifier, name: item.name, detail: typeof item.detail === "string" ? item.detail : "" };
    });
    return {
      entry_id: entry.entry_id,
      title: entry.title,
      deleted_at: entry.deleted_at,
      expires_at: typeof entry.expires_at === "string" ? entry.expires_at : null,
      deleted_by: typeof entry.deleted_by === "string" ? entry.deleted_by : null,
      size_bytes: entry.size_bytes,
      items,
    };
  });
}

export async function listTrash(signal?: AbortSignal): Promise<TrashEntry[]> {
  return parseTrashEntries(await apiFetch<unknown>(`${API}/trash`, { signal }));
}

/** Chuyển scene vào thùng rác (khôi phục được). */
export function moveSceneToTrash(projectId: string): Promise<unknown> {
  return apiFetch<unknown>(`${API}/scenes/${encodeURIComponent(projectId)}`, { method: "DELETE" });
}

/** Chuyển scene nhập vào thùng rác (khôi phục được). */
export function moveImportToTrash(importId: string): Promise<unknown> {
  return apiFetch<unknown>(`${API}/imports/${encodeURIComponent(importId)}`, { method: "DELETE" });
}

function trashAction(action: "restore" | "purge", entryIds: string[]): Promise<TrashActionResult> {
  return apiFetch<TrashActionResult>(`${API}/trash/${action}`, { method: "POST", body: JSON.stringify({ entry_ids: entryIds }) });
}

export function restoreTrash(entryIds: string[]): Promise<TrashActionResult> {
  return trashAction("restore", entryIds);
}

/** Xoá hẳn, không khôi phục được; chỉ Reviewer. */
export function purgeTrash(entryIds: string[]): Promise<TrashActionResult> {
  return trashAction("purge", entryIds);
}

/** Một chỉ số của bảng đánh giá (STUDIO_UX_SPEC.md D-16). `value` null = chưa đo; `display` nêu lý do. */
export interface EvaluationMetric {
  key: string;
  label: string;
  value: number | string | null;
  unit: string | null;
  display: string;
  meaning: string;
  verdict: "ok" | "warn" | "fail" | null;
  threshold: string | null;
}

export interface EvaluationGroup {
  group_id: string;
  title: string;
  status: "measured" | "pending" | "unavailable";
  note: string | null;
  metrics: EvaluationMetric[];
}

export interface JobEvaluation {
  job_id: string;
  scene_name: string;
  job_status: string;
  scene_revision: string | null;
  generated_at: string;
  groups: EvaluationGroup[];
}

const EVALUATION_STATUS = ["measured", "pending", "unavailable"] as const;
const EVALUATION_VERDICT = ["ok", "warn", "fail"] as const;

/** Kiểm bảng đánh giá ở biên API: thiếu field bắt buộc là lỗi, không hiện bảng dở dang như kết quả. */
export function parseJobEvaluation(data: unknown): JobEvaluation {
  const invalid = () => new ApiError(502, "Dữ liệu đánh giá không hợp lệ");
  if (!isRecord(data) || typeof data.job_id !== "string" || typeof data.scene_name !== "string" || !Array.isArray(data.groups)) throw invalid();
  const groups = data.groups.map((group): EvaluationGroup => {
    const status = isRecord(group) ? EVALUATION_STATUS.find((value) => value === group.status) : undefined;
    if (!isRecord(group) || !status || typeof group.group_id !== "string" || typeof group.title !== "string" || !Array.isArray(group.metrics)) throw invalid();
    const metrics = group.metrics.map((metric): EvaluationMetric => {
      if (!isRecord(metric) || typeof metric.key !== "string" || typeof metric.label !== "string" || typeof metric.display !== "string" || typeof metric.meaning !== "string") throw invalid();
      const value = typeof metric.value === "number" || typeof metric.value === "string" ? metric.value : null;
      return {
        key: metric.key, label: metric.label, value, display: metric.display, meaning: metric.meaning,
        unit: typeof metric.unit === "string" ? metric.unit : null,
        verdict: EVALUATION_VERDICT.find((item) => item === metric.verdict) ?? null,
        threshold: typeof metric.threshold === "string" ? metric.threshold : null,
      };
    });
    return { group_id: group.group_id, title: group.title, status, note: typeof group.note === "string" ? group.note : null, metrics };
  });
  return {
    job_id: data.job_id,
    scene_name: data.scene_name,
    job_status: typeof data.job_status === "string" ? data.job_status : "",
    scene_revision: typeof data.scene_revision === "string" ? data.scene_revision : null,
    generated_at: typeof data.generated_at === "string" ? data.generated_at : "",
    groups,
  };
}

export async function getJobEvaluation(jobId: string, signal?: AbortSignal): Promise<JobEvaluation> {
  return parseJobEvaluation(await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/evaluation`, { signal }));
}

/** Link tải báo cáo Markdown của bảng đánh giá (backend đặt tên file). */
export function evaluationReportUrl(jobId: string): string {
  return `${API}/jobs/${encodeURIComponent(jobId)}/evaluation/report.md`;
}
