/**
 * Endpoint Studio MVP. Đi qua cùng biên `fetchApi` của Web Studio; riêng upload
 * dùng XMLHttpRequest vì `fetch` chưa báo được tiến độ gửi body.
 */

import { ApiError, apiFetch, apiUrl, fetchApi, fetchConditional, type ApiResult } from "@/lib/api/client";
import type { PipelineView } from "@/lib/contracts/pipeline";
import { demoApiPath } from "@/lib/api/demo-session";
import { clearDirectUploadResume, directUpload, xhrPutPart } from "@/lib/api/directUpload";
import { verifyVideoPreparationChecksum } from "@/lib/contracts/videoPreparation";
import type { VideoPreparedArtifact } from "@/lib/media/video-normalization";
import type {
  ColliderEditCommand,
  ObjectMembershipMergeCommand,
  ObjectMembershipReassignCommand,
  ObjectRegionCommand,
  ProductArtifactRef,
  SceneEditResponse,
  SceneResponse,
  ValidationOperationStatus,
  ValidationRunStatus,
  ValidationRunView,
} from "@/lib/contracts/api";
import { VALIDATION_OPERATION_STATUSES, VALIDATION_RUN_STATUSES } from "@/lib/contracts/api";
import {
  parseDemoManifest,
  parseDemoPublishResult,
  parseDemoState,
  parseDemoSelection,
  parseMetricProposal,
  parseJobProgress,
  parseLidarMeasurements,
  parseMetricPreview,
  parseModeComparison,
  parseStageViews,
  parseSuggestResponse,
  type DemoManifest,
  type DemoPublishResult,
  type DemoSelection,
  type DemoState,
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
  type ScenarioPreferences,
  type SuggestResponse,
  type SampleSummary,
  type SceneFromUpload,
  type SceneSummary,
  type SourceRightsAttestation,
  type StageView,
  type UploadRecord,
} from "@/lib/contracts/studio";

/** Scene có phải bản demo không và có đang đúng mốc gốc không. */
export async function getDemoState(jobId: string, signal?: AbortSignal): Promise<DemoState> {
  return parseDemoState(await apiFetch<unknown>(`/api/v1/jobs/${encodeURIComponent(jobId)}/demo`, { signal }));
}

/** Reviewer lấy revision hiện tại làm bản demo gốc. */
export async function markDemo(jobId: string): Promise<DemoState> {
  return parseDemoState(await apiFetch<unknown>(`/api/v1/jobs/${encodeURIComponent(jobId)}/demo/baseline`, { method: "POST" }));
}

/** Reviewer xuất scene vào thư viện mẫu (`/new/try-demo`); `confirm_public` là xác nhận được công khai video. */
export async function publishDemo(
  jobId: string,
  body: { title?: string; description: string; confirm_public: boolean },
): Promise<DemoPublishResult> {
  return parseDemoPublishResult(await apiFetch<unknown>(`/api/v1/jobs/${encodeURIComponent(jobId)}/demo/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
}

/** Reviewer gỡ mẫu khỏi thư viện công khai, giữ nguyên dự án và artifact. */
export async function removeSample(sampleId: string): Promise<void> {
  await apiFetch(`/api/v1/samples/${encodeURIComponent(sampleId)}`, { method: "DELETE" });
}

/** Reviewer bỏ đánh dấu bản demo; nội dung scene giữ nguyên. */
export async function clearDemo(jobId: string): Promise<DemoState> {
  return parseDemoState(await apiFetch<unknown>(`/api/v1/jobs/${encodeURIComponent(jobId)}/demo/baseline`, { method: "DELETE" }));
}

/** Đưa scene về bản demo gốc bằng một revision mới; `expectedRevision` là revision đang thấy trên màn hình. */
export async function resetDemo(jobId: string, expectedRevision: string): Promise<DemoState> {
  return parseDemoState(await apiFetch<unknown>(`/api/v1/jobs/${encodeURIComponent(jobId)}/demo/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_scene_revision: expectedRevision }),
  }));
}

/** Đưa scene về bản gốc ban đầu (rev-001) bằng một revision mới; `expectedRevision` là revision đang thấy trên màn hình. */
export async function restoreRoot(jobId: string, expectedRevision: string): Promise<DemoState> {
  return parseDemoState(await apiFetch<unknown>(`/api/v1/jobs/${encodeURIComponent(jobId)}/demo/restore-root`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_scene_revision: expectedRevision }),
  }));
}

/** Kết quả xem được của từng bước (frame, camera, 3DGS, collision mesh). */
export async function getStageViews(jobId: string, signal?: AbortSignal): Promise<StageView[]> {
  const data = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/stage-views`, { signal });
  return parseStageViews(data);
}

const API = "/api/v1";

function newRunIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

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
    headers: { "Idempotency-Key": newRunIdempotencyKey() },
    body: JSON.stringify({ upload_id: uploadId, name, attestation, processing, lidar }),
  });
}

/** Thông số chỉnh được, preset và cấu hình máy worker (từ file cấu hình chung). */
export function getProcessingOptions(): Promise<ApiResult<ProcessingOptions>> {
  return fetchApi<ProcessingOptions>(`${API}/processing/options`);
}

export async function suggestProcessingPreset(
  preferences: ScenarioPreferences,
  signal?: AbortSignal,
): Promise<ApiResult<SuggestResponse>> {
  const result = await fetchApi<unknown>(`${API}/processing/suggest`, {
    method: "POST", body: JSON.stringify(preferences), signal,
  });
  if (!result.ok) return result;
  try {
    return { ok: true, data: parseSuggestResponse(result.data) };
  } catch (error) {
    return { ok: false, error: new ApiError(502, error instanceof Error ? error.message : "Gợi ý cấu hình không hợp lệ") };
  }
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

export type PipelineFetch = { notModified: true } | { notModified: false; view: PipelineView; etag: string | null };

/** Tiến trình hợp nhất của trang scene (T-060); gửi ETag để máy chủ trả 304 khi không có gì đổi. */
export async function getJobPipeline(jobId: string, etag: string | null, signal?: AbortSignal): Promise<ApiResult<PipelineFetch>> {
  const result = await fetchConditional<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/pipeline`, etag, signal);
  if (!result.ok) return result;
  if (result.data.notModified) return { ok: true, data: { notModified: true } };
  try {
    return { ok: true, data: { notModified: false, view: parsePipelineView(result.data.data), etag: result.data.etag } };
  } catch (cause) {
    return { ok: false, error: new ApiError(502, cause instanceof Error ? cause.message : "Tiến trình không hợp lệ") };
  }
}

function parsePipelineView(value: unknown): PipelineView {
  const record = value as Partial<PipelineView> | null;
  if (!record || typeof record !== "object" || !Array.isArray(record.steps) || typeof record.version !== "string"
      || !record.next_action || typeof record.next_action.kind !== "string") {
    throw new Error("Tiến trình hợp nhất không hợp lệ");
  }
  return { ...(record as PipelineView), progress: parseJobProgress(record.progress) };
}

export function cancelJob(jobId: string): Promise<unknown> {
  return apiFetch(`${API}/jobs/${encodeURIComponent(jobId)}/transitions`, {
    method: "POST",
    body: JSON.stringify({ target_status: "CANCELLED" }),
  });
}

export interface RetryJobReceipt {
  job_id: string;
  status: "QUEUED";
  job_manifest_checksum: string;
}

export async function retryJob(jobId: string): Promise<RetryJobReceipt> {
  const result = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
    headers: { "Idempotency-Key": newRunIdempotencyKey() },
  });
  if (!isRecord(result) || result.job_id !== jobId || result.status !== "QUEUED" || typeof result.job_manifest_checksum !== "string") {
    throw new ApiError(502, "Backend trả trạng thái chấp nhận retry không hợp lệ");
  }
  return result as unknown as RetryJobReceipt;
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
  return demoApiPath(`${API}/samples/${encodeURIComponent(sampleId)}/files/${encodeURIComponent(name)}`);
}

export interface UploadHandle {
  promise: Promise<UploadRecord>;
  abort: () => void;
}

export interface UploadVideoOptions {
  resumeIdentity?: string;
  keepResumeKey?: boolean;
  temporary?: boolean;
  onUploadId?: (uploadId: string) => void;
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
  options: UploadVideoOptions = {},
): UploadHandle {
  const controller = new AbortController();
  let proxy: UploadHandle | null = null;
  const promise = (async () => {
    const config = await apiFetch<{ direct: boolean; max_bytes: number }>(`${API}/uploads/config`);
    if (file.size > config.max_bytes) {
      throw new ApiError(413, `Video vượt giới hạn ${formatLimit(config.max_bytes)}`);
    }
    if (!config.direct) {
      proxy = proxyUpload(file, onProgress, options.temporary);
      if (controller.signal.aborted) proxy.abort();
      return proxy.promise;
    }
    const state = await directUpload(
      file,
      {
        onProgress,
        onVerifying,
        signal: controller.signal,
        resumeIdentity: options.resumeIdentity,
        keepResumeKey: options.keepResumeKey,
        temporary: options.temporary,
        onStarted: options.onUploadId,
      },
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

export interface PreparedVideoUploadOptions {
  accountId: string;
  onProgress: (fraction: number) => void;
  onVerifying?: () => void;
  onUploadedRecord?: (record: UploadRecord) => void;
  existingRecord?: UploadRecord | null;
  temporary?: boolean;
  onUploadId?: (uploadId: string) => void;
}

interface PreparedVideoUploadDependencies {
  upload: typeof uploadVideo;
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
  storage: () => Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
}

const preparedVideoUploadDependencies: PreparedVideoUploadDependencies = {
  upload: uploadVideo,
  api: apiFetch,
  storage: browserStorage,
};

function readStoredUploadId(storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null, key: string): string | null {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function storeUploadId(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null,
  key: string,
  uploadId: string | null,
): void {
  try {
    if (uploadId === null) storage?.removeItem(key);
    else storage?.setItem(key, uploadId);
  } catch {
    // Upload remains usable in this tab; a denied storage only disables reload recovery.
  }
}

function belongsToAccount(record: UploadRecord, accountId: string): boolean {
  return accountId === "local" || accountId === "anonymous"
    ? record.uploaded_by == null
    : record.uploaded_by?.user_id === accountId;
}

function matchesPreparedUpload(record: UploadRecord, accountId: string, prepared: VideoPreparedArtifact): boolean {
  return belongsToAccount(record, accountId) && record.input_kind === "rgb_video" &&
    record.media_type === "video/mp4" && record.size_bytes === prepared.file.size &&
    record.checksum === prepared.manifest.prepared_file.checksum;
}

async function findPreparedUpload(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null,
  key: string,
  accountId: string,
  prepared: VideoPreparedArtifact,
  api: PreparedVideoUploadDependencies["api"],
  signal: AbortSignal,
): Promise<UploadRecord | null> {
  const savedId = readStoredUploadId(storage, key);
  if (!savedId) return null;
  const uploads = await api<{ uploads: UploadRecord[] }>(`${API}/uploads`, { signal });
  const record = uploads.uploads.find((item) => item.upload_id === savedId) ?? null;
  const matches = record !== null && matchesPreparedUpload(record, accountId, prepared);
  if (!matches) storeUploadId(storage, key, null);
  return matches ? record : null;
}

/** Upload finalized bytes, then bind and verify the preparation receipt and source-frame map. */
export function uploadPreparedVideo(
  prepared: VideoPreparedArtifact,
  options: PreparedVideoUploadOptions,
  dependencies: PreparedVideoUploadDependencies = preparedVideoUploadDependencies,
): UploadHandle {
  const controller = new AbortController();
  let activeUpload: UploadHandle | null = null;
  const identity = `${options.accountId}:${prepared.manifest.prepared_file.checksum}:${prepared.manifest.preparation_checksum}`;
  const storageKey = `r2s-prepared-upload:v1:${encodeURIComponent(identity)}`;
  const directStorage = dependencies.storage();
  const promise = (async () => {
    if (prepared.file.size !== prepared.manifest.prepared_file.size_bytes ||
        prepared.frameMapFile.size !== prepared.manifest.frame_map.size_bytes) {
      throw new ApiError(422, "Video đã chuẩn bị không khớp với bản gốc. Hãy tải lại video.");
    }
    await verifyVideoPreparationChecksum(prepared.manifest);
    let record = options.existingRecord && matchesPreparedUpload(options.existingRecord, options.accountId, prepared)
      ? options.existingRecord
      : null;
    record ??= await findPreparedUpload(
      directStorage, storageKey, options.accountId, prepared, dependencies.api, controller.signal,
    );
    if (!record) {
      activeUpload = dependencies.upload(
        prepared.file,
        options.onProgress,
        options.onVerifying,
        { resumeIdentity: identity, keepResumeKey: true, temporary: options.temporary, onUploadId: options.onUploadId },
      );
      if (controller.signal.aborted) activeUpload.abort();
      record = await activeUpload.promise;
      storeUploadId(directStorage, storageKey, record.upload_id);
    }
    options.onUploadedRecord?.(record);
    if (controller.signal.aborted) throw new ApiError(499, "Đã hủy xác minh video.");

    const uploadId = encodeURIComponent(record.upload_id);
    await dependencies.api<UploadRecord>(`${API}/uploads/${uploadId}/video-preparation/manifest`, {
      method: "PUT",
      body: JSON.stringify(prepared.manifest),
      signal: controller.signal,
    });
    options.onVerifying?.();
    const verified = await dependencies.api<UploadRecord>(`${API}/uploads/${uploadId}/video-preparation/frame-map`, {
      method: "PUT",
      headers: { "Content-Type": "application/x-ndjson" },
      body: prepared.frameMapFile,
      signal: controller.signal,
    });
    storeUploadId(directStorage, storageKey, null);
    clearDirectUploadResume(prepared.file, identity, directStorage);
    return verified;
  })();

  const abort = () => {
    controller.abort();
    activeUpload?.abort();
  };
  return { promise, abort };
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
function proxyUpload(file: File, onProgress: (fraction: number) => void, temporary = false): UploadHandle {
  const request = new XMLHttpRequest();
  const promise = new Promise<UploadRecord>((resolve, reject) => {
    request.open("POST", demoApiPath(`${API}/uploads?filename=${encodeURIComponent(file.name)}${temporary ? "&temporary=true" : ""}`));
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

/** Số đo và nguồn tỉ lệ của scene: đề xuất MoGe-2, kết quả đã xác nhận, LiDAR. */
export async function getModeComparison(jobId: string, signal?: AbortSignal): Promise<ModeComparison> {
  const data = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/metric/comparison`, { signal });
  return parseModeComparison(data);
}

/** Tạo scene import từ upload PLY/COLMAP hoặc SOG; standalone worker publish bản xem. */
export function createImport(uploadId: string, name: string, idempotencyKey = newRunIdempotencyKey()): Promise<ImportedScene> {
  return apiFetch<ImportedScene>(`${API}/imports`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ upload_id: uploadId, name }),
  });
}

export function getImport(importId: string, signal?: AbortSignal): Promise<ApiResult<ImportedScene>> {
  return fetchApi<ImportedScene>(`${API}/imports/${encodeURIComponent(importId)}`, { signal });
}

export function retryImport(importId: string): Promise<ImportedScene> {
  return apiFetch<ImportedScene>(`${API}/imports/${encodeURIComponent(importId)}/retry`, { method: "POST" });
}

export function cancelImport(importId: string): Promise<ImportedScene> {
  return apiFetch<ImportedScene>(`${API}/imports/${encodeURIComponent(importId)}/cancel`, { method: "POST" });
}

export function listImports(): Promise<ApiResult<{ imports: ImportedScene[] }>> {
  return fetchApi<{ imports: ImportedScene[] }>(`${API}/imports`);
}

/** URL SOG của scene import (tên file `.sog` để viewer chọn đúng parser). */
export function importContentUrl(importId: string): string {
  return `${API}/imports/${encodeURIComponent(importId)}/content/scene.sog`;
}

/** Lưu góc nhìn camera mặc định của scene import (hoặc gỡ nếu null). */
export function updateImportCamera(
  importId: string,
  camera: { position: [number, number, number]; target: [number, number, number]; fov?: number } | null,
): Promise<ImportedScene> {
  if (camera === null) {
    return clearImportCamera(importId);
  }
  return apiFetch<ImportedScene>(`${API}/imports/${encodeURIComponent(importId)}/camera`, {
    method: "PATCH",
    body: JSON.stringify(camera),
  });
}

/** Gỡ bookmark góc nhìn mặc định của scene import, quay lại góc nhìn tự động ban đầu. */
export function clearImportCamera(importId: string): Promise<ImportedScene> {
  return apiFetch<ImportedScene>(`${API}/imports/${encodeURIComponent(importId)}/camera`, {
    method: "DELETE",
  });
}

// ── vật thể trong SceneIR (PRODUCT-07/07A, ADR 0006) ─────────────────────────

/** SceneIR hiện tại của job; 404 khi bước tách vật thể chưa publish revision nào. */
/** T-063: bản scene đã tải gần nhất theo job (kèm ETag) và request đang bay, dùng chung cho mọi component của trang. */
const sceneCache = new Map<string, { etag: string; data: SceneResponse }>();
const sceneInFlight = new Map<string, Promise<ApiResult<SceneResponse>>>();

/** Request đọc đang bay theo khoá (gói, trạng thái duyệt): các panel hỏi cùng lúc dùng chung; xong là quên, lần sau hỏi lại. */
const sharedInFlight = new Map<string, Promise<unknown>>();

/** Chỉ cho test: xoá bộ đệm scene giữa các ca. */
export function clearSceneCache(): void {
  sceneCache.clear();
  sceneInFlight.clear();
  sharedInFlight.clear();
}

/** `signal` chỉ để caller thôi chờ; request chung không bị hủy theo một caller. */
async function shareInFlight<T>(key: string, signal: AbortSignal | undefined, load: () => Promise<T>): Promise<T> {
  let pending = sharedInFlight.get(key) as Promise<T> | undefined;
  if (!pending) {
    pending = load().finally(() => sharedInFlight.delete(key));
    sharedInFlight.set(key, pending);
  }
  const value = await pending;
  if (signal?.aborted) throw new DOMException("đã hủy", "AbortError");
  return value;
}

async function loadJobScene(jobId: string): Promise<ApiResult<SceneResponse>> {
  const cached = sceneCache.get(jobId);
  const result = await fetchConditional<SceneResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene`, cached?.etag ?? null);
  if (!result.ok) return result;
  if (result.data.notModified) {
    return cached ? { ok: true, data: cached.data } : { ok: false, error: new ApiError(502, "Máy chủ trả 304 khi chưa có scene") };
  }
  if (result.data.etag) sceneCache.set(jobId, { etag: result.data.etag, data: result.data.data });
  return { ok: true, data: result.data.data };
}

/**
 * SceneIR hiện tại (T-063): các component hỏi cùng lúc dùng chung một request; lần sau gửi ETag, máy chủ trả 304 thì dùng
 * lại đúng đối tượng đã parse (không tải lại ~650 KB, không parse lại, React thấy cùng tham chiếu). `signal` chỉ để caller
 * bỏ qua kết quả; request chung không bị hủy theo một caller.
 */
export async function getJobScene(jobId: string, signal?: AbortSignal): Promise<ApiResult<SceneResponse>> {
  let pending = sceneInFlight.get(jobId);
  if (!pending) {
    pending = loadJobScene(jobId).finally(() => sceneInFlight.delete(jobId));
    sceneInFlight.set(jobId, pending);
  }
  const result = await pending;
  if (signal?.aborted) return { ok: false, error: new ApiError(0, "đã hủy") };
  return result;
}

/** Choose one allow-listed LiDAR candidate; the server reruns eligibility and owns the revision CAS. */
export function selectLidarCollisionSource(
  jobId: string,
  command: { expected_scene_revision: string; candidate_manifest_ref: ProductArtifactRef },
): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/collision-source/lidar`, {
    method: "POST",
    body: JSON.stringify(command),
  });
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

/** Merge persisted Gaussian ownership and return the canonical regenerated scene revision. */
export function mergeObjectCandidates(jobId: string, command: ObjectMembershipMergeCommand): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/corrections/merge`, {
    method: "POST",
    body: JSON.stringify(command),
  });
}

/** Reassign a bounded source-frame ROI and return the canonical regenerated scene revision. */
export function reassignObjectMembership(
  jobId: string,
  command: ObjectMembershipReassignCommand,
): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/corrections/reassign`, {
    method: "POST",
    body: JSON.stringify(command),
  });
}

/** Bộ đếm và mẫu của một lần xem trước vùng. Preview không ghi gì và không đổi revision (architecture.md §7.3). */
export interface RegionPreview {
  scene_revision: string;
  membership_checksum: string;
  object_id: string;
  added_count: number;
  removed_count: number;
  object_gaussian_count: number;
  protected_floor_count: number;
  overlaps: Record<string, number>;
  claimed: Record<string, number>;
  /** Object-local, tối đa 20 000 điểm mỗi loại. */
  added_sample_m: [number, number, number][];
  removed_sample_m: [number, number, number][];
  shell_glb_base64: string | null;
  shell_error: string | null;
  shell_sample_rows?: number;
  /** Số Gaussian còn lại của từng vật "Lấy luôn" sau khi áp box (T-024). */
  donor_remaining?: Record<string, number>;
  /** Vật "Lấy luôn" sẽ còn dưới tối thiểu nếu áp box này: Apply bị khoá tới khi bỏ tick hoặc thu box. */
  blockers?: { object_id: string; remaining: number; minimum: number }[];
}

export function previewObjectRegion(
  jobId: string,
  objectId: string,
  command: ObjectRegionCommand,
  signal?: AbortSignal,
): Promise<RegionPreview> {
  return apiFetch<RegionPreview>(
    `${API}/jobs/${encodeURIComponent(jobId)}/scene/objects/${encodeURIComponent(objectId)}/region/preview`,
    { method: "POST", body: JSON.stringify(command), signal },
  );
}

/** Box ban đầu của "Chỉnh vùng": bao đúng các Gaussian hiện có của vật, object-local (T-023). Chỉ đọc. */
export interface RegionFit {
  scene_revision: string;
  membership_checksum: string;
  object_id: string;
  center_m: [number, number, number];
  half_extents_m: [number, number, number];
  yaw_rad: number;
  rows: number;
}

export function fetchRegionFit(
  jobId: string,
  objectId: string,
  revision: string,
  signal?: AbortSignal,
): Promise<RegionFit> {
  const query = new URLSearchParams({ expected_scene_revision: revision });
  return apiFetch<RegionFit>(
    `${API}/jobs/${encodeURIComponent(jobId)}/scene/objects/${encodeURIComponent(objectId)}/region/fit?${query}`,
    { signal },
  );
}

/** Draft: 201 với revision mới. Ready: 202 với tiến độ dựng lại (T-011). Dùng `isSceneEditResponse` để phân biệt. */
export function applyObjectRegion(
  jobId: string,
  objectId: string,
  command: ObjectRegionCommand,
): Promise<SceneEditResponse | ObjectifyState> {
  return apiFetch<SceneEditResponse | ObjectifyState>(
    `${API}/jobs/${encodeURIComponent(jobId)}/scene/objects/${encodeURIComponent(objectId)}/region/apply`,
    { method: "POST", body: JSON.stringify(command) },
  );
}

/** Phản hồi apply là revision mới (Draft) hay tiến độ dựng lại (Ready): phân biệt theo dạng JSON, không theo mã HTTP. */
export function isSceneEditResponse(value: SceneEditResponse | ObjectifyState): value is SceneEditResponse {
  return "scene" in value && "scene_revision" in value;
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

/** Ghi kích thước/local pose của box collider thành revision SceneIR kế tiếp. */
export function editCollider(jobId: string, command: ColliderEditCommand): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/collider`, {
    method: "POST",
    body: JSON.stringify(command),
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

export type ObjectifyMode = "objectify" | "boxes" | "membership" | "geometry" | "region";

export type OperationResource = "vram" | "ram" | "disk";
export type OperationWaitReason = "busy" | "external" | "exceeds_machine" | "unmeasured" | "gate_error";

export interface ObjectifyResourceWait {
  status: "waiting_resources" | "waiting_gpu_affinity" | "worker_busy" | "identity_conflict";
  required_gb: Record<OperationResource, number | null>;
  available_gb: Record<OperationResource, number | null>;
  capacity_gb: Record<OperationResource, number | null>;
  waiting_on: OperationResource[];
  reasons: Partial<Record<OperationResource, OperationWaitReason>>;
  needs_exclusive_gpu: boolean;
}

/** Trạng thái tách theo vật của scene + yêu cầu dựng lại gần nhất (worker thực hiện). */
export interface ObjectifyState {
  operation_id?: string | null;
  phase?: string | null;
  status: "idle" | "queued" | "running" | "done" | "failed" | "cancelled";
  mode: ObjectifyMode | null;
  /** Revision SceneIR hiện tại; API cũ không gửi. */
  scene_revision?: string | null;
  /** Tách theo vật lỗi hết số lần thử; scene chỉ có môi trường, chờ người dùng chọn. */
  awaiting_choice: boolean;
  object_centric: boolean;
  /** Máy xử lý có runtime tách theo vật. */
  available: boolean;
  note: string | null;
  base_revision: string | null;
  result_revision: string | null;
  error: string | null;
  /** False means the same input cannot recover by repeating objectify. Older APIs omit this. */
  retryable?: boolean | null;
  floor_fit?: Record<string, unknown> | null;
  /** Snapshot tài nguyên khiến request vẫn queued; không chứa worker identity/lease token. */
  resource_wait: ObjectifyResourceWait | null;
  /** Running operation has received a cancel request and is stopping/reaping its child. */
  cancellation_requested: boolean;
  /** Trạng thái hình học theo vật của scene; null = scene cũ không có khoá (luồng cũ, T-021). */
  object_geometry?: "awaiting_review" | "ready" | null;
  geometry_note?: string | null;
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

/** Xếp hàng tạo mesh theo vật trên đúng revision Draft đang hiển thị (architecture.md §7.4). */
export function buildObjectGeometry(jobId: string, expectedRevision: string): Promise<ObjectifyState> {
  return apiFetch<ObjectifyState>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/geometry/build`, {
    method: "POST",
    body: JSON.stringify({ expected_scene_revision: expectedRevision }),
  });
}

/** Cancel queued work or request a running objectify worker to stop its child process. */
export function cancelObjectify(jobId: string, operationId?: string | null): Promise<ObjectifyState> {
  return apiFetch<ObjectifyState>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/objectify/cancel${operationId ? `?operation_id=${encodeURIComponent(operationId)}` : ""}`, {
    method: "POST",
  });
}

// ── gói mô phỏng Isaac (EX-SIM SIM-02…05) ───────────────────────────────────

export interface PreflightRuleView {
  rule_id: string;
  result: "PASS" | "FAIL" | "WARN" | string;
  affected_object_ids: string[];
  remediation: string | null;
}

export interface ExportCapabilityIssueView {
  code: string;
  message: string;
  affected_object_ids: string[];
}

export interface ExportCapabilityView {
  scene_revision: string;
  scene_ir_checksum: string;
  status: "supported" | "blocked";
  requested_mode: "auto";
  effective_mode: "legacy_box" | "hybrid";
  builder_version: string;
  runtime_qualification: "not_required" | "qualified" | "failed";
  runtime_version: string | null;
  requirements: {
    collider_types: string[];
    static_physics: boolean;
    dynamic_physics: boolean;
    local_collider_offsets: boolean;
    hybrid_visuals: boolean;
    external_assets: boolean;
  };
  blockers: ExportCapabilityIssueView[];
  /** Lưu ý không chặn xuất (vd. vật danh mục xuất bằng hộp); vắng ở backend cũ nên coi là rỗng. */
  notices: ExportCapabilityIssueView[];
}

/** Tập con của `SimulationPackage` backend mà UI hiển thị; các field khác bỏ qua. */
export interface SimulationPackageView {
  scene_revision: string;
  source_scene_revision: string;
  created_at: string;
  confirmed_objects: number;
  environment_triangles: number;
  carved_triangles: number;
  /** Tam giác nền được giữ vì hộp nguồn chung với vật không bị khoét; vắng ở backend cũ nên coi là 0. */
  retained_shared_triangles: number;
  retained_shared_object_ids: string[];
  preflight: { blocking_result: string; rules: PreflightRuleView[] };
  export_capability: ExportCapabilityView | null;
  package_ref: { artifact_uri: string; artifact_checksum: string } | null;
}

function parseExportCapability(value: unknown): ExportCapabilityView | null {
  if (value === null || value === undefined) return null;
  if (!isObject(value)) throw new ApiError(502, "Backend trả capability USD sai contract");

  const requirements = value.requirements;
  const validRequirements =
    isObject(requirements) &&
    Array.isArray(requirements.collider_types) &&
    requirements.collider_types.every((item) => typeof item === "string") &&
    [
      "static_physics",
      "dynamic_physics",
      "local_collider_offsets",
      "hybrid_visuals",
      "external_assets",
    ].every((key) => typeof requirements[key] === "boolean");
  const validIssues = (items: unknown) =>
    Array.isArray(items) &&
    items.every(
      (item) =>
        isObject(item) &&
        typeof item.code === "string" &&
        typeof item.message === "string" &&
        Array.isArray(item.affected_object_ids) &&
        item.affected_object_ids.every((id) => typeof id === "string"),
    );
  const notices = value.notices ?? [];
  if (
    typeof value.scene_revision !== "string" ||
    typeof value.scene_ir_checksum !== "string" ||
    !["supported", "blocked"].includes(String(value.status)) ||
    value.requested_mode !== "auto" ||
    !["legacy_box", "hybrid"].includes(String(value.effective_mode)) ||
    typeof value.builder_version !== "string" ||
    !["not_required", "qualified", "failed"].includes(String(value.runtime_qualification)) ||
    !(value.runtime_version === null || typeof value.runtime_version === "string") ||
    !validRequirements ||
    !validIssues(value.blockers) ||
    !validIssues(notices)
  ) {
    throw new ApiError(502, "Backend trả capability USD sai contract");
  }
  return { ...value, notices } as unknown as ExportCapabilityView;
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
  const exportCapability = parseExportCapability(data.export_capability);
  if (exportCapability?.status === "blocked" && data.package_ref != null) {
    throw new ApiError(502, "Backend trả candidate dù capability USD đang bị chặn");
  }
  const { retained_shared_triangles: retained = 0, retained_shared_object_ids: retainedIds = [] } = data;
  if (
    !Number.isSafeInteger(retained) || retained < 0 ||
    !Array.isArray(retainedIds) || !retainedIds.every((id) => typeof id === "string")
  ) {
    throw new ApiError(502, "Backend trả số tam giác dùng chung sai contract");
  }
  return {
    ...data,
    retained_shared_triangles: retained,
    retained_shared_object_ids: retainedIds,
    export_capability: exportCapability,
  } as SimulationPackageView;
}

/** Gói của revision scene hiện tại; null khi chưa tạo hoặc scene đã sửa sau lần tạo. */
export async function getSimulationPackage(jobId: string, signal?: AbortSignal): Promise<SimulationPackageView | null> {
  return shareInFlight(`package:${jobId}`, signal, async () =>
    parseSimulationPackage(await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/simulation-package`)),
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
  return demoApiPath(`${API}/jobs/${encodeURIComponent(jobId)}/training-recording.rrd`);
}

export function simulationPackageDownloadUrl(jobId: string): string {
  return demoApiPath(`${API}/jobs/${encodeURIComponent(jobId)}/simulation-package/download`);
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

export type CollisionObservationStateView = "observed_static" | "unobserved" | "inferred" | "motion_suspected";

export interface CollisionPathSupportView {
  pair_id: string;
  state: CollisionObservationStateView;
  observation_ids: string[];
  coverage_fraction: number;
  diagnostic_ref: EvidenceRefView | null;
}

export interface ValidationReportView {
  overall_result: string;
  validator_version: string;
  candidate_checksum: string | null;
  report_checksum: string | null;
  environment_versions: Record<string, string>;
  checks: ValidationCheckView[];
  path_results: PathResultView[];
  collision_quality_ref: EvidenceRefView | null;
  collision_path_support: CollisionPathSupportView[];
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
  /** True chỉ khi backend xác minh selected worker run, candidate/config/report và RuntimeManifest cùng identity. */
  isaac_runtime_proof: boolean | null;
  /** Warning IDs từ gate; optional path warning dùng `path:<pair_id>`. */
  warning_ids: string[];
  /** Tên hiển thị của người duyệt (backend điền từ tài khoản); null thì UI hiện id. */
  reviewer_name?: string | null;
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
  release_seal_error: string | null;
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
  const collisionStates = new Set<CollisionObservationStateView>([
    "observed_static",
    "unobserved",
    "inferred",
    "motion_suspected",
  ]);
  const rows = (items: unknown, key: "check_id" | "pair_id") =>
    (Array.isArray(items) ? items : []).flatMap((item) => {
      const id = isObject(item) ? text(item[key]) : null;
      if (!isObject(item) || !id) return [];
      return [{ id, result: text(item.result) ?? "?", message: text(item.message), evidence_refs: evidenceRefs(item.evidence_refs) }];
    });
  const versions = isObject(value.environment_versions) ? value.environment_versions : {};
  const collisionSupport = (Array.isArray(value.collision_path_support) ? value.collision_path_support : []).flatMap((item) => {
    if (!isObject(item)) return [];
    const pairId = text(item.pair_id);
    const state = text(item.state);
    const coverage = item.coverage_fraction;
    if (
      !pairId ||
      !state ||
      !collisionStates.has(state as CollisionObservationStateView) ||
      typeof coverage !== "number" ||
      !Number.isFinite(coverage) ||
      coverage < 0 ||
      coverage > 1
    ) {
      return [];
    }
    return [{
      pair_id: pairId,
      state: state as CollisionObservationStateView,
      observation_ids: strings(item.observation_ids),
      coverage_fraction: coverage,
      diagnostic_ref: evidenceRefs([item.diagnostic_ref])[0] ?? null,
    }];
  });
  return {
    overall_result: text(value.overall_result) ?? "?",
    validator_version: text(value.validator_version) ?? "?",
    candidate_checksum: text(value.candidate_checksum),
    report_checksum: text(value.report_checksum),
    environment_versions: Object.fromEntries(Object.entries(versions).flatMap(([key, version]) => (typeof version === "string" ? [[key, version]] : []))),
    checks: rows(value.checks, "check_id").map(({ id, ...rest }) => ({ check_id: id, ...rest })),
    path_results: rows(value.path_results, "pair_id").map(({ id, ...rest }) => ({ pair_id: id, ...rest })),
    collision_quality_ref: evidenceRefs([value.collision_quality_ref])[0] ?? null,
    collision_path_support: collisionSupport,
  };
}

function parseValidationRun(value: unknown): ValidationRunView {
  if (!isObject(value)) throw new ApiError(502, "Backend trả validation run sai contract");
  const jobId = text(value.job_id);
  const runId = text(value.run_id);
  const sceneRevision = text(value.scene_revision);
  const candidateChecksum = text(value.candidate_checksum);
  const configChecksum = text(value.validation_config_checksum);
  const requestedAt = text(value.requested_at);
  const runStatus = VALIDATION_RUN_STATUSES.find((item) => item === value.run_status);
  const status = VALIDATION_OPERATION_STATUSES.find((item) => item === value.status);
  const attempt = value.attempt;
  if (
    value.schema_version !== "1.0" ||
    !jobId ||
    !runId ||
    typeof attempt !== "number" ||
    !Number.isSafeInteger(attempt) ||
    attempt < 1 ||
    !sceneRevision ||
    !candidateChecksum ||
    !configChecksum ||
    !runStatus ||
    !status ||
    !requestedAt ||
    (value.started_at !== null && typeof value.started_at !== "string") ||
    (value.completed_at !== null && typeof value.completed_at !== "string") ||
    (value.report_checksum !== null && typeof value.report_checksum !== "string") ||
    typeof value.selected !== "boolean" ||
    typeof value.retryable !== "boolean" ||
    (value.error_code !== null && typeof value.error_code !== "string")
  ) {
    throw new ApiError(502, "Backend trả validation run sai contract");
  }
  return {
    schema_version: "1.0",
    job_id: jobId,
    run_id: runId,
    attempt,
    scene_revision: sceneRevision,
    candidate_checksum: candidateChecksum,
    validation_config_checksum: configChecksum,
    run_status: runStatus as ValidationRunStatus,
    status: status as ValidationOperationStatus,
    requested_at: requestedAt,
    started_at: value.started_at as string | null,
    completed_at: value.completed_at as string | null,
    report_checksum: value.report_checksum as string | null,
    selected: value.selected,
    retryable: value.retryable,
    error_code: value.error_code as string | null,
  };
}

export async function listValidationRuns(jobId: string, signal?: AbortSignal): Promise<ValidationRunView[]> {
  const value = await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/validation-runs`, { signal });
  if (!Array.isArray(value)) throw new ApiError(502, "Backend trả validation history sai contract");
  return value.map(parseValidationRun);
}

export async function submitValidationRun(jobId: string, candidateChecksum: string): Promise<ValidationRunView> {
  return parseValidationRun(await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/validation-runs`, {
    method: "POST",
    headers: { "Idempotency-Key": newRunIdempotencyKey() },
    body: JSON.stringify({ candidate_checksum: candidateChecksum }),
  }));
}

export async function cancelValidationRun(jobId: string, runId: string): Promise<ValidationRunView> {
  return parseValidationRun(await apiFetch<unknown>(
    `${API}/jobs/${encodeURIComponent(jobId)}/validation-runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  ));
}

export async function retryValidationRun(jobId: string, runId: string): Promise<ValidationRunView> {
  return parseValidationRun(await apiFetch<unknown>(
    `${API}/jobs/${encodeURIComponent(jobId)}/validation-runs/${encodeURIComponent(runId)}/retry`,
    { method: "POST", headers: { "Idempotency-Key": newRunIdempotencyKey() } },
  ));
}

export async function selectValidationRun(
  jobId: string,
  runId: string,
  candidateChecksum: string,
  expectedSelectedRunId: string | null,
): Promise<ValidationRunView> {
  return parseValidationRun(await apiFetch<unknown>(
    `${API}/jobs/${encodeURIComponent(jobId)}/validation-runs/${encodeURIComponent(runId)}/select`,
    {
      method: "POST",
      body: JSON.stringify({
        candidate_checksum: candidateChecksum,
        expected_selected_run_id: expectedSelectedRunId,
      }),
    },
  ));
}

export function validationArtifactUrl(jobId: string, runId: string, artifactName: string): string {
  return demoApiPath(`${API}/jobs/${encodeURIComponent(jobId)}/validation-runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactName)}`);
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
    reviewer_name: text(value.reviewer_name),
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
    release_seal_error: text(value.release_seal_error),
    blockers: strings(value.blockers),
  };
}

export async function getReviewState(jobId: string, signal?: AbortSignal): Promise<ReviewStateView> {
  return shareInFlight(`review:${jobId}`, signal, async () =>
    parseReviewState(await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/review-state`)),
  );
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
  return demoApiPath(`${API}/jobs/${encodeURIComponent(jobId)}/release-download`);
}

/** Một thứ nằm trong mục thùng rác: scene, scene nhập, hoặc upload chỉ scene đó dùng. */
export interface TrashItem {
  kind: "scene" | "import" | "upload";
  identifier: string;
  name: string;
  detail: string;
}

/** Một mục thùng rác. */
export interface TrashEntry {
  entry_id: string;
  title: string;
  deleted_at: string;
  /** Thời điểm mục tự bị xoá hẳn; null khi deployment tắt tự xoá. */
  expires_at: string | null;
  deleted_by: string | null;
  size_bytes: number;
  items: TrashItem[];
  capabilities?: { can_restore: boolean; can_purge: boolean };
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
    let capabilities: TrashEntry["capabilities"];
    if (entry.capabilities !== undefined) {
      if (
        !isRecord(entry.capabilities) || typeof entry.capabilities.can_restore !== "boolean" ||
        typeof entry.capabilities.can_purge !== "boolean"
      ) throw new ApiError(502, "Quyền thùng rác không hợp lệ");
      capabilities = { can_restore: entry.capabilities.can_restore, can_purge: entry.capabilities.can_purge };
    }
    return {
      entry_id: entry.entry_id,
      title: entry.title,
      deleted_at: entry.deleted_at,
      expires_at: typeof entry.expires_at === "string" ? entry.expires_at : null,
      deleted_by: typeof entry.deleted_by === "string" ? entry.deleted_by : null,
      size_bytes: entry.size_bytes,
      items,
      capabilities,
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

/** Một chỉ số của bảng đánh giá. `value` null = chưa đo; `display` nêu lý do. */
export interface EvaluationMetric {
  key: string;
  label: string;
  value: number | string | null;
  unit: string | null;
  display: string;
  meaning: string;
  verdict: "ok" | "warn" | "fail" | null;
  threshold: string | null;
  reference: string | null;
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
  summary: string[];
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
        reference: typeof metric.reference === "string" ? metric.reference : null,
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
    summary: Array.isArray(data.summary) ? data.summary.filter((s): s is string => typeof s === "string") : [],
    groups,
  };
}

export async function getJobEvaluation(jobId: string, signal?: AbortSignal): Promise<JobEvaluation> {
  return parseJobEvaluation(await apiFetch<unknown>(`${API}/jobs/${encodeURIComponent(jobId)}/evaluation`, { signal }));
}

/** Link tải báo cáo Markdown của bảng đánh giá (backend đặt tên file). */
export function evaluationReportUrl(jobId: string): string {
  return demoApiPath(`${API}/jobs/${encodeURIComponent(jobId)}/evaluation/report.md`);
}


export interface CollisionSurfacePlane {
  id: string;
  kind: "floor" | "wall";
  source_checksum: string;
  fill_regions?: boolean;
  points: [[number,number,number],[number,number,number],[number,number,number]];
}
export function editCollisionSurface(jobId: string, command: {
  expected_scene_revision: string; source_checksum: string; action: "mark" | "remove" | "fill";
  kind?: "floor" | "wall"; points?: CollisionSurfacePlane["points"]; plane_id?: string;
}): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/collision-surfaces`, {
    method: "POST", body: JSON.stringify(command),
  });
}

export interface MembershipPreview {
  scene_revision: string;
  membership_checksum: string;
  source_visual_checksum: string;
  source_object_id: string | null;
  target_object_id: string | null;
  affected_object_ids: string[];
  gaussian_count: number;
  protected_count: number;
  wrong_owner_count: number;
  source_gaussian_indices: number[];
  remaining_gaussians: Record<string, number>;
}

export function previewMembership(jobId: string, command: ObjectMembershipReassignCommand): Promise<MembershipPreview> {
  return apiFetch<MembershipPreview>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/membership/preview`, {
    method: "POST", body: JSON.stringify(command),
  });
}

export function regenerateMembership(jobId: string, command: ObjectMembershipReassignCommand): Promise<ObjectifyState> {
  return apiFetch<ObjectifyState>(`${API}/jobs/${encodeURIComponent(jobId)}/scene/membership/regenerate`, {
    method: "POST", body: JSON.stringify(command),
  });
}
