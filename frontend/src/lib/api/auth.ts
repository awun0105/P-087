/**
 * Client đăng nhập và quản lý role. Cookie phiên httpOnly do backend đặt qua
 * proxy `/api/v1` cùng domain — JavaScript không đọc được token.
 */

import { apiFetch, fetchApi, ApiError, type ApiResult } from "@/lib/api/client";

export type Role = "guest" | "editor" | "reviewer";
export type InviteRole = "editor" | "reviewer";

export interface PublicUser {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
  active: boolean;
  daily_job_quota: number;
}

export interface GuestQuotaSummary {
  policy_id: "guest_calendar_day_v1";
  limit: 3;
  used: number;
  remaining: number;
  window_start_utc: string;
  resets_at_utc: string;
  timezone: "Asia/Ho_Chi_Minh";
}

export interface Me {
  auth_required: boolean;
  /** Missing on older API deployments; unknown is treated as closed by the UI. */
  guest_signup_enabled?: boolean;
  user: PublicUser | null;
  /** Present for Guest sessions on quota-aware API deployments. */
  quota?: GuestQuotaSummary | null;
}

/** Branch only on the stable quota code; never infer exhaustion from localized message text. */
export function isGuestQuotaExceededError(error: unknown): error is ApiError {
  if (!(error instanceof ApiError) || error.status !== 429) return false;
  try {
    const detail: unknown = JSON.parse(error.detail);
    return typeof detail === "object" && detail !== null && "code" in detail && detail.code === "guest_daily_job_quota_exceeded";
  } catch {
    return false;
  }
}

const API = "/api/v1/auth";

export function getMe(signal?: AbortSignal): Promise<ApiResult<Me>> {
  return fetchApi<Me>(`${API}/me`, { signal });
}

export function login(email: string, password: string): Promise<PublicUser> {
  return apiFetch<PublicUser>(`${API}/login`, { method: "POST", body: JSON.stringify({ email, password }) });
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API}/logout`, { method: "POST", cache: "no-store" });
  if (!response.ok) throw new ApiError(response.status, "Không đăng xuất được.");
}

export function register(input: {
  invite_code?: string;
  email: string;
  display_name: string;
  password: string;
}): Promise<PublicUser> {
  return apiFetch<PublicUser>(`${API}/register`, { method: "POST", body: JSON.stringify(input) });
}

export function registerGuest(input: { email: string; display_name: string; password: string }): Promise<PublicUser> {
  return apiFetch<PublicUser>(`${API}/register/guest`, { method: "POST", body: JSON.stringify(input) });
}

export function createInvite(role: InviteRole): Promise<{ code: string; role: InviteRole; expires_at: string }> {
  return apiFetch(`${API}/invites`, { method: "POST", body: JSON.stringify({ role }) });
}

export function listUsers(): Promise<ApiResult<PublicUser[]>> {
  return fetchApi<PublicUser[]>(`${API}/users`);
}

export function updateUser(
  userId: string,
  changes: Partial<Pick<PublicUser, "role" | "active" | "daily_job_quota">>,
): Promise<PublicUser> {
  return apiFetch<PublicUser>(`${API}/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

/** Reviewer có mọi quyền của Editor (PRD §3.4). */
export function canEdit(me: Me | null): boolean {
  return me !== null && (!me.auth_required || me.user !== null);
}

/** Resource mutation uses the server's explicit owner capability; older APIs fail closed for Guest. */
export function resourceCapabilityAllowed(me: Me | null, serverAllowed?: boolean): boolean {
  if (serverAllowed !== undefined) return serverAllowed;
  return canEdit(me) && me?.user?.role !== "guest";
}

/**
 * Quyết định duyệt/phát hành luôn cần phiên Reviewer, kể cả khi deployment tắt đăng nhập
 * (backend `_reviewer()` trả 401 khi không có phiên); khác `isReviewer` dùng cho các route quản trị.
 */
export function canDecideReview(me: Me | null): boolean {
  return me?.user?.role === "reviewer";
}

export function isReviewer(me: Me | null): boolean {
  return me !== null && (!me.auth_required || me.user?.role === "reviewer");
}
