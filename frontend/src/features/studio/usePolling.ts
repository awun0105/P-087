"use client";

import { useEffect, useRef } from "react";

/**
 * Gọi `task` ngay rồi lặp lại sau mỗi `intervalMs` khi `active`; dừng hẳn khi
 * unmount hoặc tab ẩn để không bắn request vô ích. Request đang bay bị abort.
 */
export function usePolling(task: (signal: AbortSignal) => Promise<void>, intervalMs: number, active: boolean): void {
  const latest = useRef(task);
  useEffect(() => {
    latest.current = task;
  }, [task]);

  useEffect(() => {
    if (!active) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let stopped = false;

    const tick = async () => {
      if (stopped) return;
      if (document.visibilityState === "visible") {
        controller = new AbortController();
        try {
          await latest.current(controller.signal);
        } catch {
          // Lỗi mạng được task tự hiển thị; vòng poll vẫn tiếp tục.
        }
      }
      if (!stopped) timer = setTimeout(tick, intervalMs);
    };
    void tick();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, active]);
}
