/**
 * Ranh giới gọi API duy nhất của Web Studio.
 *
 * Hai quyết định ở đây:
 *
 * 1. **Không ném lỗi ra UI.** `fetchApi` trả `ApiResult` để màn hình buộc phải
 *    xử lý nhánh lỗi — "UI reflects backend state and explicit errors" là điều
 *    kiện DoD của PRODUCT-05, mà `throw` thì dễ bị nuốt thành màn hình trắng.
 *    `apiFetch` (ném lỗi) chỉ dành cho event handler đã có chỗ bắt.
 *
 * 2. **Server và browser dùng base khác nhau.** Browser gọi đường dẫn tương đối
 *    để đi qua rewrite của Next (không cần CORS); RSC không có origin nên phải
 *    gọi thẳng backend bằng `REAL2SIM_API_URL`.
 */

import { demoApiPath } from "./demo-session";

const SERVER_BASE = process.env.REAL2SIM_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** Lỗi do dữ liệu client gửi lên, khác với lỗi hạ tầng. */
  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500;
  }
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

function apiBase(): string {
  return typeof window === "undefined" ? SERVER_BASE : "";
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = await response.text();
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") {
      return new ApiError(response.status, parsed.detail);
    }
    // FastAPI trả `detail` dạng list cho lỗi validate của Pydantic.
    if (parsed.detail !== undefined) {
      return new ApiError(response.status, JSON.stringify(parsed.detail));
    }
  } catch {
    // Body không phải JSON: rơi xuống dùng text thô.
  }
  return new ApiError(response.status, body || `HTTP ${response.status}`);
}

export async function fetchApi<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${apiBase()}${demoApiPath(path)}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
    if (!response.ok) {
      return { ok: false, error: await toApiError(response) };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (cause) {
    return { ok: false, error: new ApiError(0, `không gọi được backend: ${String(cause)}`) };
  }
}

/** Kết quả GET có ETag: 304 → `notModified`; 200 → dữ liệu kèm ETag mới (T-060). */
export type ConditionalResult<T> = { notModified: true } | { notModified: false; data: T; etag: string | null };

export async function fetchConditional<T>(
  path: string,
  etag: string | null,
  signal?: AbortSignal,
): Promise<ApiResult<ConditionalResult<T>>> {
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (etag) headers["If-None-Match"] = etag;
    const response = await fetch(`${apiBase()}${demoApiPath(path)}`, { headers, cache: "no-store", signal });
    if (response.status === 304) return { ok: true, data: { notModified: true } };
    if (!response.ok) return { ok: false, error: await toApiError(response) };
    return { ok: true, data: { notModified: false, data: (await response.json()) as T, etag: response.headers?.get?.("ETag") ?? null } };
  } catch (cause) {
    return { ok: false, error: new ApiError(0, `không gọi được backend: ${String(cause)}`) };
  }
}

/** Biến thể ném lỗi, dùng trong event handler đã có `try`/`catch`. */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const result = await fetchApi<T>(path, init);
  if (!result.ok) {
    throw result.error;
  }
  return result.data;
}

export function apiUrl(path: string, params: Record<string, string | readonly string[]>): string {
  // Mảng thành tham số lặp lại (`?dynamic=a&dynamic=b`), đúng cách FastAPI đọc `list[str]`.
  const query = new URLSearchParams(
    Object.entries(params).flatMap(([key, value]) => (typeof value === "string" ? [[key, value]] : value.map((item) => [key, item]))),
  ).toString();
  return `${apiBase()}${demoApiPath(path)}?${query}`;
}
