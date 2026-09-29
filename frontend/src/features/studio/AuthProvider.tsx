"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { getMe, logout as apiLogout, type Me } from "@/lib/api/auth";

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

  const refresh = useCallback(async () => {
    const result = await getMe();
    // Backend không trả được: coi như khách của deployment bắt đăng nhập (an toàn hơn).
    setMe(result.ok ? result.data : { auth_required: true, user: null });
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(timer);
  }, [refresh]);

  const logout = useCallback(async () => {
    await apiLogout();
    await refresh();
  }, [refresh]);

  const value = useMemo(() => ({ me, refresh, logout }), [me, refresh, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth cần nằm trong AuthProvider");
  return state;
}
