import { ApiError, apiFetch, fetchApi, type ApiResult } from "@/lib/api/client";

export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject;
export interface JsonObject { [key: string]: JsonValue }

export type RegistrationMode = "registered_map" | "static_cloud";
export type RegistrationFinding =
  | "SOURCE_FORMAT_REQUIRED"
  | "SOURCE_HEADER_REQUIRED"
  | "SOURCE_UNITS_REQUIRED"
  | "SOURCE_FRAME_REQUIRED"
  | "SAME_SCENE_CONTEXT_MISSING"
  | "DIFFERENT_SCENE"
  | "EMPTY_CLOUD"
  | "POINT_COUNT_UNAVAILABLE"
  | "POINT_BUDGET_EXCEEDED"
  | "RAW_SCANS_REQUIRE_TRAJECTORY"
  | "METRIC_SCALE_UNKNOWN"
  | "FLOOR_UNSUPPORTED"
  | "FLOOR_UNCERTAIN"
  | "TARGET_FLOOR_EVIDENCE_REQUIRED"
  | "LOW_OVERLAP"
  | "LOW_COVERAGE"
  | "HIGH_RESIDUAL"
  | "AMBIGUOUS_CANDIDATES"
  | "UNOBSERVABLE"
  | "SEARCH_BUDGET_EXCEEDED"
  | "ICP_NOT_CONVERGED"
  | "STALE_TARGET"
  | "UNQUALIFIED_PROFILE"
  | "METRIC_CONFIRMATION_REQUIRED";

export interface RegistrationRequestPayload extends JsonObject {
  request_id: string;
  requested_by: string;
  target_project_id: string;
  target_job_id: string;
  expected_scene_revision: string;
  request_checksum: string;
  source: JsonObject & { mode: RegistrationMode; target_job_id: string };
}

export interface RegistrationPreflight {
  request_checksum: string;
  state: "READY" | "INSUFFICIENT";
  findings: RegistrationFinding[];
}

export interface RegistrationPreparation {
  request: RegistrationRequestPayload;
  preflight: RegistrationPreflight;
}

export type RegistrationOperationState =
  | "REQUESTED"
  | "QUEUED"
  | "RUNNING"
  | "WAITING_RESOURCES"
  | "PROPOSED"
  | "AMBIGUOUS"
  | "INSUFFICIENT"
  | "FAILED"
  | "REVIEWED"
  | "CONFIRMED"
  | "COMMITTED"
  | "CANCELLED";

export interface RegistrationOperation {
  operation_id: string;
  job_id: string;
  state: RegistrationOperationState;
  attempt: number;
  created_at: string;
  updated_at: string;
  proposal_ref: JsonObject | null;
  qa_report_ref: JsonObject | null;
  cancellation_requested: boolean;
}

const REGISTRATION_STATES = new Set<RegistrationOperationState>([
  "REQUESTED", "QUEUED", "RUNNING", "WAITING_RESOURCES", "PROPOSED", "AMBIGUOUS",
  "INSUFFICIENT", "FAILED", "REVIEWED", "CONFIRMED", "COMMITTED", "CANCELLED",
]);
const REGISTRATION_FINDINGS = new Set<RegistrationFinding>([
  "SOURCE_FORMAT_REQUIRED", "SOURCE_HEADER_REQUIRED", "SOURCE_UNITS_REQUIRED", "SOURCE_FRAME_REQUIRED",
  "SAME_SCENE_CONTEXT_MISSING", "DIFFERENT_SCENE", "EMPTY_CLOUD", "POINT_COUNT_UNAVAILABLE",
  "POINT_BUDGET_EXCEEDED", "RAW_SCANS_REQUIRE_TRAJECTORY", "METRIC_SCALE_UNKNOWN", "FLOOR_UNSUPPORTED",
  "FLOOR_UNCERTAIN", "TARGET_FLOOR_EVIDENCE_REQUIRED", "LOW_OVERLAP", "LOW_COVERAGE", "HIGH_RESIDUAL",
  "AMBIGUOUS_CANDIDATES", "UNOBSERVABLE", "SEARCH_BUDGET_EXCEEDED", "ICP_NOT_CONVERGED", "STALE_TARGET",
  "UNQUALIFIED_PROFILE", "METRIC_CONFIRMATION_REQUIRED",
]);
const STATES_CANCELLABLE = new Set<RegistrationOperationState>([
  "QUEUED", "RUNNING", "WAITING_RESOURCES",
]);
const STATES_WITH_FUTURE_TRANSITIONS = new Set<RegistrationOperationState>([
  "REQUESTED", "QUEUED", "RUNNING", "WAITING_RESOURCES", "PROPOSED", "AMBIGUOUS", "REVIEWED", "CONFIRMED",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") return true;
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

export function parseRegistrationRequest(value: unknown): RegistrationRequestPayload {
  if (!isRecord(value) || !Object.values(value).every(isJsonValue)) {
    throw new Error("request phải là một JSON object");
  }
  const source = value.source;
  if (
    typeof value.request_id !== "string" || value.request_id.length < 1 || value.request_id.length > 128
    || typeof value.requested_by !== "string" || typeof value.target_project_id !== "string"
    || typeof value.target_job_id !== "string" || typeof value.expected_scene_revision !== "string"
    || typeof value.request_checksum !== "string" || !isRecord(source)
    || (source.mode !== "registered_map" && source.mode !== "static_cloud")
    || source.target_job_id !== value.target_job_id
  ) {
    throw new Error("request không khớp registration contract");
  }
  return value as unknown as RegistrationRequestPayload;
}

function parsePreflight(value: unknown, request: RegistrationRequestPayload): RegistrationPreflight {
  if (!isRecord(value) || !Array.isArray(value.findings)) throw new Error("preflight sai contract");
  const state = value.state;
  const findings = value.findings;
  if (
    value.request_checksum !== request.request_checksum
    || (state !== "READY" && state !== "INSUFFICIENT")
    || !findings.every((item) => typeof item === "string" && REGISTRATION_FINDINGS.has(item as RegistrationFinding))
    || (state === "READY" && findings.length !== 0)
    || (state === "INSUFFICIENT" && findings.length === 0)
  ) {
    throw new Error("preflight không khớp request hoặc chứa findings không hợp lệ");
  }
  return { request_checksum: request.request_checksum, state, findings: findings as RegistrationFinding[] };
}

export function parseRegistrationPreparation(value: unknown): RegistrationPreparation {
  if (!isRecord(value)) throw new Error("preparation response phải là object");
  const request = parseRegistrationRequest(value.request);
  return { request, preflight: parsePreflight(value.preflight, request) };
}

export function parseRegistrationOperation(value: unknown, jobId: string): RegistrationOperation {
  if (!isRecord(value)) throw new Error("operation response phải là object");
  if (
    typeof value.operation_id !== "string" || typeof value.job_id !== "string" || value.job_id !== jobId
    || typeof value.state !== "string" || !REGISTRATION_STATES.has(value.state as RegistrationOperationState)
    || !Number.isInteger(value.attempt) || (value.attempt as number) < 0
    || typeof value.created_at !== "string" || typeof value.updated_at !== "string"
    || typeof value.cancellation_requested !== "boolean"
    || (value.proposal_ref !== null && !isRecord(value.proposal_ref))
    || (value.qa_report_ref !== null && !isRecord(value.qa_report_ref))
  ) {
    throw new Error("operation response không khớp registration contract");
  }
  return value as unknown as RegistrationOperation;
}

function badResponse(cause: unknown): ApiError {
  return new ApiError(502, cause instanceof Error ? cause.message : "Registration API trả dữ liệu sai contract");
}

const API = "/api/v1/jobs";
const registrationPath = (jobId: string) => `${API}/${encodeURIComponent(jobId)}/rgb-lidar-registration`;

export async function prepareRegistration(jobId: string, expectedSceneRevision: string): Promise<RegistrationPreparation> {
  const value = await apiFetch<unknown>(`${registrationPath(jobId)}/prepare`, {
    method: "POST",
    body: JSON.stringify({ expected_scene_revision: expectedSceneRevision }),
  });
  try {
    const preparation = parseRegistrationPreparation(value);
    if (preparation.request.target_job_id !== jobId || preparation.request.expected_scene_revision !== expectedSceneRevision) {
      throw new Error("preparation is not bound to the current job and scene revision");
    }
    return preparation;
  } catch (cause) {
    throw badResponse(cause);
  }
}

export async function enqueueRegistration(
  jobId: string,
  request: RegistrationRequestPayload,
): Promise<RegistrationOperation> {
  const value = await apiFetch<unknown>(`${registrationPath(jobId)}/operations`, {
    method: "POST",
    headers: { "Idempotency-Key": request.request_id },
    body: JSON.stringify(request),
  });
  try {
    return parseRegistrationOperation(value, jobId);
  } catch (cause) {
    throw badResponse(cause);
  }
}

export async function getRegistrationOperation(
  jobId: string,
  operationId: string,
  signal?: AbortSignal,
): Promise<ApiResult<RegistrationOperation>> {
  const result = await fetchApi<unknown>(`${registrationPath(jobId)}/operations/${encodeURIComponent(operationId)}`, { signal });
  if (!result.ok) return result;
  try {
    return { ok: true, data: parseRegistrationOperation(result.data, jobId) };
  } catch (cause) {
    return { ok: false, error: badResponse(cause) };
  }
}

export async function cancelRegistrationOperation(jobId: string, operationId: string): Promise<RegistrationOperation> {
  const value = await apiFetch<unknown>(
    `${registrationPath(jobId)}/operations/${encodeURIComponent(operationId)}/cancel`,
    { method: "POST" },
  );
  try {
    return parseRegistrationOperation(value, jobId);
  } catch (cause) {
    throw badResponse(cause);
  }
}

export function isRegistrationOperationActive(state: RegistrationOperationState): boolean {
  return STATES_CANCELLABLE.has(state);
}

export function isRegistrationOperationPollable(state: RegistrationOperationState): boolean {
  return STATES_WITH_FUTURE_TRANSITIONS.has(state);
}
