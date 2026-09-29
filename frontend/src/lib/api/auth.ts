/**
 * Client đăng nhập hai role (ADR 0003 §3). Cookie phiên httpOnly do backend đặt qua
 * proxy `/api/v1` cùng domain — JavaScript không đọc được token.
 */

import { apiFetch, fetchApi, type ApiResult } from "@/lib/api/client";

export type Role = "editor" | "reviewer";

export interface PublicUser {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
  active: boolean;
  daily_job_quota: number;
}

export interface Me {
  auth_required: boolean;
  user: PublicUser | null;
}

const API = "/api/v1/auth";

export function getMe(): Promise<ApiResult<Me>> {
  return fetchApi<Me>(`${API}/me`);
}

export function login(email: string, password: string): Promise<PublicUser> {
  return apiFetch<PublicUser>(`${API}/login`, { method: "POST", body: JSON.stringify({ email, password }) });
}

export async function logout(): Promise<void> {
  await fetch(`${API}/logout`, { method: "POST", cache: "no-store" });
}

export function register(input: {
  invite_code: string;
  email: string;
  display_name: string;
  password: string;
}): Promise<PublicUser> {
  return apiFetch<PublicUser>(`${API}/register`, { method: "POST", body: JSON.stringify(input) });
}

export function createInvite(role: Role): Promise<{ code: string; role: Role; expires_at: string }> {
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

export function isReviewer(me: Me | null): boolean {
  return me !== null && (!me.auth_required || me.user?.role === "reviewer");
}
