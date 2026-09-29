/**
 * Endpoint product, gõ kiểu đầy đủ.
 *
 * Không endpoint nào nhận hay trả đường dẫn filesystem. `artifactContentUrl`
 * chỉ dựng URL từ `artifact://` URI + checksum, và backend vẫn đối chiếu lại
 * với allow-list của job — client không tự quyết định được đọc artifact nào.
 */

import type {
  ArtifactList,
  JobAttemptList,
  JobCreateRequest,
  JobList,
  JobManifest,
  Project,
  ProjectList,
  ReviewState,
  SceneEditCommand,
  SceneEditResponse,
  SceneResponse,
  TransitionRequest,
  ValidationState,
} from "@/lib/contracts/api";
import { apiFetch, apiUrl, fetchApi, type ApiResult } from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import { parsePreview, type ReconstructionPreview } from "@/lib/contracts/preview";

const PRODUCT = "/api/v1";

function jsonPost(body: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(body) };
}

// ── projects ────────────────────────────────────────────────────────────────

export function listProjects(): Promise<ApiResult<ProjectList>> {
  return fetchApi<ProjectList>(`${PRODUCT}/projects`);
}

export function getProject(projectId: string): Promise<ApiResult<Project>> {
  return fetchApi<Project>(`${PRODUCT}/projects/${encodeURIComponent(projectId)}`);
}

export function listJobs(projectId: string): Promise<ApiResult<JobList>> {
  return fetchApi<JobList>(`${PRODUCT}/projects/${encodeURIComponent(projectId)}/jobs`);
}

export function createJob(projectId: string, request: JobCreateRequest = {}): Promise<JobManifest> {
  return apiFetch<JobManifest>(
    `${PRODUCT}/projects/${encodeURIComponent(projectId)}/jobs`,
    jsonPost(request),
  );
}

// ── jobs ────────────────────────────────────────────────────────────────────

export function getJob(jobId: string): Promise<ApiResult<JobManifest>> {
  return fetchApi<JobManifest>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}`);
}

export function listJobArtifacts(jobId: string): Promise<ApiResult<ArtifactList>> {
  return fetchApi<ArtifactList>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/artifacts`);
}

export function listJobAttempts(jobId: string): Promise<ApiResult<JobAttemptList>> {
  return fetchApi<JobAttemptList>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/attempts`);
}

export function transitionJob(jobId: string, request: TransitionRequest): Promise<JobManifest> {
  return apiFetch<JobManifest>(
    `${PRODUCT}/jobs/${encodeURIComponent(jobId)}/transitions`,
    jsonPost(request),
  );
}

export function retryJob(jobId: string): Promise<JobManifest> {
  return apiFetch<JobManifest>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
  });
}

// ── scene (PRODUCT-06) ──────────────────────────────────────────────────────

export function getScene(jobId: string): Promise<ApiResult<SceneResponse>> {
  return fetchApi<SceneResponse>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/scene`);
}

export async function getPreview(jobId: string): Promise<ApiResult<ReconstructionPreview>> {
  const result = await fetchApi<unknown>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/preview`);
  if (!result.ok) return result;
  try {
    return { ok: true, data: parsePreview(result.data, jobId) };
  } catch {
    return { ok: false, error: new ApiError(502, "Backend trả preview sai contract/job identity") };
  }
}

export function editScene(jobId: string, command: SceneEditCommand): Promise<SceneEditResponse> {
  return apiFetch<SceneEditResponse>(
    `${PRODUCT}/jobs/${encodeURIComponent(jobId)}/scene/edits`,
    jsonPost(command),
  );
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

// ── validation và review ────────────────────────────────────────────────────

export function getValidation(jobId: string): Promise<ApiResult<ValidationState>> {
  return fetchApi<ValidationState>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/validation`);
}

export function getReview(jobId: string): Promise<ApiResult<ReviewState>> {
  return fetchApi<ReviewState>(`${PRODUCT}/jobs/${encodeURIComponent(jobId)}/review`);
}
