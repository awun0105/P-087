"use client";

import { useEffect, useRef } from "react";

/**
 * Gọi `task` ngay rồi lặp lại sau mỗi `intervalMs` khi `active`; dừng hẳn khi
 * unmount hoặc tab ẩn để không bắn request vô ích. Request đang bay bị abort.
 */
export function usePolling(task: (signal: AbortSignal) => Promise<void>, intervalMs: number, active: boolean, key?: any): void {
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
    // Quay lại tab: cập nhật ngay thay vì chờ hết chu kỳ (có thể 20 s) mới thấy trạng thái mới.
    const onVisible = () => {
      if (document.visibilityState !== "visible" || stopped) return;
      if (timer) clearTimeout(timer);
      controller?.abort();
      void tick();
    };
    document.addEventListener("visibilitychange", onVisible);
    void tick();
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisible);
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, active, key]);
}
