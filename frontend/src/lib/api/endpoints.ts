/**
 * Endpoint product mà Studio dùng, gõ kiểu đầy đủ (project, job, attempt, preview, bytes artifact).
 *
 * Không endpoint nào nhận hay trả đường dẫn filesystem. `artifactContentUrl`
 * chỉ dựng URL từ `artifact://` URI + checksum, và backend vẫn đối chiếu lại
 * với allow-list của job — client không tự quyết định được đọc artifact nào.
 */

import type { ArtifactList, JobAttemptList, JobManifest, Project } from "@/lib/contracts/api";
import { apiFetch, apiUrl, fetchApi, type ApiResult } from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import { parsePreview, type ReconstructionPreview } from "@/lib/contracts/preview";

const PRODUCT = "/api/v1";

// ── projects ────────────────────────────────────────────────────────────────

export function getProject(projectId: string): Promise<ApiResult<Project>> {
  return fetchApi<Project>(`${PRODUCT}/projects/${encodeURIComponent(projectId)}`);
}

// ── jobs ────────────────────────────────────────────────────────────────────

export function getJob(jobId: string): Promise<ApiResult<JobManifest>> {
  return fetchApi<JobManifest>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}`);
}

export function listJobArtifacts(jobId: string, signal?: AbortSignal): Promise<ApiResult<ArtifactList>> {
  return fetchApi<ArtifactList>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/artifacts`, { signal });
}

export function listJobAttempts(jobId: string): Promise<ApiResult<JobAttemptList>> {
  return fetchApi<JobAttemptList>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/attempts`);
}

export function retryJob(jobId: string): Promise<JobManifest> {
  return apiFetch<JobManifest>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
  });
}

// ── preview và artifact (PRODUCT-06) ────────────────────────────────────────

export async function getPreview(jobId: string): Promise<ApiResult<ReconstructionPreview>> {
  const result = await fetchApi<unknown>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/preview`);
  if (!result.ok) return result;
  try {
    return { ok: true, data: parsePreview(result.data, jobId) };
  } catch {
    return { ok: false, error: new ApiError(502, "Backend trả preview sai contract/job identity") };
  }
}

/**
 * URL tải bytes của một artifact.
 *
 * `artifact_uri` phải nằm trong allow-list của job; backend trả 404 nếu không.
 * Checksum đi kèm để backend verify bytes trước khi trả.
 */
export function jobArtifactContentUrl(
  jobId: string,
  ref: { artifact_uri: string; artifact_checksum: string },
): string {
  const filename = ref.artifact_uri.split("/").pop();
  return apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}/artifacts/content/${encodeURIComponent(filename ?? "artifact")}`, {
    artifact_uri: ref.artifact_uri,
    artifact_checksum: ref.artifact_checksum,
  });
}

/** Ảnh frame thu nhỏ (JPEG, T-066); cùng allow-list với `jobArtifactContentUrl`. `width` ∈ 160/320/640. */
export function jobFrameThumbnailUrl(
  jobId: string,
  ref: { artifact_uri: string; artifact_checksum: string },
  width: 160 | 320 | 640 = 320,
): string {
  return apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}/frames/thumbnail`, {
    artifact_uri: ref.artifact_uri,
    artifact_checksum: ref.artifact_checksum,
    width: String(width),
  });
}

/** Gaussian của vật dạng PLY nén (T-067); máy chủ chuyển hướng về PLY gốc khi không nén được. Chỉ cho `ObjectGaussians`. */
export function jobCompactGaussiansUrl(jobId: string, ref: { artifact_uri: string; artifact_checksum: string }): string {
  return apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}/objects/compact`, {
    artifact_uri: ref.artifact_uri,
    artifact_checksum: ref.artifact_checksum,
  });
}

/** Lớp LiDAR đã căn chỉnh của scene (float32 xyz, mét, Z-up); `key` đổi theo bản căn chỉnh để cache đúng bản. */
export function jobLidarOverlayUrl(jobId: string, key: string): string {
  return apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}/lidar-overlay`, { v: key });
}

/**
 * Lưới va chạm của job đã xoay sang không gian hiển thị, cho chế độ đi bộ của viewer. Đường dẫn
 * giữ đuôi `.glb` vì viewer chọn loader theo đuôi file. `dynamic`: id vật động — vùng gốc của chúng
 * được khoét khỏi lưới để người đi chạm và đẩy được vật (ADR 0010).
 */
export function jobWalkCollisionUrl(
  jobId: string,
  ref: { artifact_uri: string; artifact_checksum: string },
  dynamic: readonly string[] = [],
  sceneRevision?: string,
  frame: "canonical" | "display" = "display",
  preview = false,
  reconstruction = false,
): string {
  const filename = ref.artifact_uri.split("/").pop();
  return apiUrl(`/api/v1/jobs/${encodeURIComponent(jobId)}/walk-collision/${encodeURIComponent(filename ?? "collision.glb")}`, {
    artifact_uri: ref.artifact_uri,
    artifact_checksum: ref.artifact_checksum,
    ...(sceneRevision ? { scene_revision: sceneRevision, frame, ...(preview ? { preview: "true" } : {}) } : {}),
    ...(dynamic.length ? { dynamic: [...dynamic].sort() } : {}),
    ...(reconstruction ? { reconstruction: "true" } : {}),
  });
}
