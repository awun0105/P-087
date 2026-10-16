"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { getMe, logout as apiLogout, type Me } from "@/lib/api/auth";
import { clearStudioDrafts } from "@/features/studio/drafts";
import { notifySuccess, ErrorFeedback } from "@/components/studio/feedback";
import { errorMessage } from "@/lib/ui-error";

const SESSION_CHECK_TIMEOUT_MS = 10_000;

interface AuthState {
  /** `null` khi đang tải lần đầu. */
  me: Me | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/**
 * Trạng thái đăng nhập dùng chung trong Studio. Nguồn sự thật là backend (`/auth/me`);
 * đây chỉ là bản đọc để UI ẩn/hiện nút — backend vẫn kiểm quyền trên từng route.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    // Backend treo không được giữ màn "Đang kiểm tra phiên" mãi: quá hạn thì báo lỗi và để người dùng thử lại.
    const result = await getMe(AbortSignal.timeout(SESSION_CHECK_TIMEOUT_MS));
    // Backend không trả được: coi như khách của deployment bắt đăng nhập (an toàn hơn).
    setMe(result.ok ? result.data : { auth_required: true, user: null });
    setError(result.ok ? null : errorMessage(result.error));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(timer);
  }, [refresh]);

  const logout = useCallback(async () => {
    await apiLogout();
    clearStudioDrafts();
    await refresh();
    notifySuccess("Đã đăng xuất.");
  }, [refresh]);

  const value = useMemo(() => ({ me, refresh, logout }), [me, refresh, logout]);
  return <AuthContext.Provider value={value}>{error && <ErrorFeedback className="mx-4 mt-4" message={"Chưa xác minh được phiên tài khoản. " + error} retry={() => void refresh()} />}{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth cần nằm trong AuthProvider");
  return state;
}
