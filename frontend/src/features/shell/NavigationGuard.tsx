"use client";

import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/shadcn/alert-dialog";

export interface LeaveCheck {
  dirty: () => Promise<boolean>;
  warnOnUnload: () => boolean;
  releases: (href: string) => boolean;
}
interface Guard {
  register: (check: LeaveCheck) => () => void;
  navigate: (action: () => void, href?: string, release?: boolean) => Promise<boolean>;
  needsCheck: (href: string) => boolean;
}
const fallback: Guard = { register: () => () => {}, navigate: async (action) => { action(); return true; }, needsCheck: () => false };
const Context = createContext<Guard>(fallback);
const INDEX = "__studioHistoryIndex";
function historyIndex(state: unknown): number | null {
  if (!state || typeof state !== "object") return null;
  const value = (state as Record<string, unknown>)[INDEX];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
function withIndex(state: unknown, index: number): Record<string, unknown> {
  return { ...(state && typeof state === "object" ? state : {}), [INDEX]: index };
}

/** Guard của host: không sửa vendor, không làm mất metadata history của Next. */
export function NavigationGuardProvider({ children }: { children: ReactNode }) {
  const checks = useRef(new Set<LeaveCheck>());
  const pending = useRef<((leave: boolean) => void) | null>(null);
  const checking = useRef(false);
  const [open, setOpen] = useState(false);
  const ask = useCallback(async (href?: string, release = false): Promise<boolean> => {
    if (checking.current) return false;
    checking.current = true;
    try {
      for (const check of checks.current) {
        if (!release && href && !check.releases(href)) continue;
        let dirty = true;
        try { dirty = await check.dirty(); } catch { /* Không biết trạng thái iframe: hỏi trước khi bỏ phiên. */ }
        if (dirty) return await new Promise<boolean>((resolve) => { pending.current = resolve; setOpen(true); });
      }
      return true;
    } finally { checking.current = false; }
  }, []);
  const settle = useCallback((leave: boolean) => { pending.current?.(leave); pending.current = null; setOpen(false); }, []);
  const navigate = useCallback(async (action: () => void, href?: string, release = false) => {
    if (!await ask(href, release)) return false;
    action();
    return true;
  }, [ask]);
  const needsCheck = useCallback((href: string) => [...checks.current].some((check) => check.releases(href)), []);
  const register = useCallback((check: LeaveCheck) => { checks.current.add(check); return () => { checks.current.delete(check); }; }, []);
  useEffect(() => {
    let index = historyIndex(history.state) ?? 0;
    const originalPush = history.pushState;
    const originalReplace = history.replaceState;
    originalReplace.call(history, withIndex(history.state, index), "");
    const push: History["pushState"] = (state, unused, url) => { originalPush.call(history, withIndex(state, index + 1), unused, url); index += 1; };
    const replace: History["replaceState"] = (state, unused, url) => { originalReplace.call(history, withIndex(state, index), unused, url); };
    history.pushState = push;
    history.replaceState = replace;
    let restoring: (() => void) | null = null;
    let allowOnce = false;
    let moving = false;
    const onPop = (event: PopStateEvent) => {
      const target = historyIndex(event.state);
      if (restoring) { event.stopImmediatePropagation(); const done = restoring; restoring = null; done(); return; }
      if (allowOnce) { allowOnce = false; if (target !== null) index = target; return; }
      if (target === null || !needsCheck(window.location.href)) { if (target !== null) index = target; return; }
      const delta = target - index;
      if (!delta) return;
      event.stopImmediatePropagation();
      if (moving) return;
      moving = true;
      const destination = window.location.href;
      // Quay về entry nguồn trước khi hỏi: iframe chưa bị Next unmount.
      void new Promise<void>((resolve) => { restoring = resolve; history.go(-delta); }).then(async () => {
        if (await ask(destination)) { allowOnce = true; history.go(delta); }
        moving = false;
      });
    };
    const unload = (event: BeforeUnloadEvent) => {
      if ([...checks.current].some((check) => check.warnOnUnload())) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("popstate", onPop, true);
    window.addEventListener("beforeunload", unload);
    return () => {
      if (history.pushState === push) history.pushState = originalPush;
      if (history.replaceState === replace) history.replaceState = originalReplace;
      window.removeEventListener("popstate", onPop, true);
      window.removeEventListener("beforeunload", unload);
      pending.current?.(false);
    };
  }, [ask, needsCheck]);
  return <Context.Provider value={{ register, navigate, needsCheck }}>
    {children}
    <AlertDialog open={open} onOpenChange={(value) => { if (!value) settle(false); }}>
      <AlertDialogContent><AlertDialogHeader>
        <AlertDialogTitle>Rời phiên chỉnh Gaussian?</AlertDialogTitle>
        <AlertDialogDescription>Thay đổi trong editor chưa được xuất thành file, hoặc chưa kiểm tra được trạng thái editor. Chọn Ở lại để dùng File › Export; rời phiên sẽ bỏ các thay đổi cục bộ.</AlertDialogDescription>
      </AlertDialogHeader><AlertDialogFooter>
        <AlertDialogCancel onClick={() => settle(false)}>Ở lại</AlertDialogCancel>
        <AlertDialogAction onClick={() => settle(true)}>Rời và bỏ thay đổi</AlertDialogAction>
      </AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
  </Context.Provider>;
}
export function useNavigationGuard(): Guard { return useContext(Context); }

/** Link được guard theo onNavigate của Next 16; click mở tab mới vẫn hoạt động. */
export function GuardedLink(props: ComponentProps<typeof NextLink>) {
  const guard = useNavigationGuard();
  return guard === fallback ? <NextLink {...props} /> : <ActiveGuardedLink {...props} />;
}
function ActiveGuardedLink(props: ComponentProps<typeof NextLink>) {
  const guard = useNavigationGuard();
  const router = useRouter();
  return <NextLink {...props} onNavigate={(event) => {
    props.onNavigate?.(event);
    const href = typeof props.href === "string" ? props.href : "";
    if (href && guard.needsCheck(href)) { event.preventDefault(); void guard.navigate(() => router.push(href), href); }
  }} />;
}
