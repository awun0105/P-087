/**
 * Endpoint Studio MVP. Đi qua cùng biên `fetchApi` của Web Studio; riêng upload
 * dùng XMLHttpRequest vì `fetch` chưa báo được tiến độ gửi body.
 */

import { ApiError, apiFetch, fetchApi, type ApiResult } from "@/lib/api/client";
import {
  parseDemoManifest,
  parseJobProgress,
  type DemoManifest,
  type JobProgress,
  type ParamValue,
  type ProcessingEvaluation,
  type ProcessingOptions,
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

export async function getDemo(): Promise<ApiResult<DemoManifest>> {
  const result = await fetchApi<unknown>(`${API}/demo`);
  if (!result.ok) return result;
  try {
    return { ok: true, data: parseDemoManifest(result.data) };
  } catch (cause) {
    return { ok: false, error: new ApiError(502, cause instanceof Error ? cause.message : "Demo không hợp lệ") };
  }
}

/** URL tương đối cùng origin để cả `<img>` và editor nhúng dùng được. */
export function demoFileUrl(name: string): string {
  return `${API}/demo/files/${encodeURIComponent(name)}`;
}

export interface UploadHandle {
  promise: Promise<UploadRecord>;
  abort: () => void;
}

/** Stream file lên `/uploads`; `onProgress` nhận tỉ lệ bytes đã gửi (đo thật, 0..1). */
export function uploadVideo(file: File, onProgress: (fraction: number) => void): UploadHandle {
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
