/**
 * Endpoint Studio MVP. Đi qua cùng biên `fetchApi` của Web Studio; riêng upload
 * dùng XMLHttpRequest vì `fetch` chưa báo được tiến độ gửi body.
 */

import { ApiError, apiFetch, fetchApi, type ApiResult } from "@/lib/api/client";
import { directUpload, xhrPutPart } from "@/lib/api/directUpload";
import {
  parseDemoManifest,
  parseDemoSelection,
  parseJobProgress,
  parseLidarMeasurements,
  parseMetricPreview,
  type DemoManifest,
  type DemoSelection,
  type JobProgress,
  type LidarMeasurements,
  type MetricInput,
  type MetricPoint,
  type MetricPreview,
  type ParamValue,
  type ProcessingEvaluation,
  type ProcessingOptions,
  type SampleSummary,
  type SceneFromUpload,
  type SceneSummary,
  type SourceRightsAttestation,
  type UploadRecord,
} from "@/lib/contracts/studio";

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
): Promise<SceneFromUpload> {
  return apiFetch<SceneFromUpload>(`${API}/scenes/from-upload`, {
    method: "POST",
    body: JSON.stringify({ upload_id: uploadId, name, attestation, processing }),
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
