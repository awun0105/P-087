"use client";

import { useEffect, useRef } from "react";

/**
 * Gọi `task` ngay rồi lặp lại sau mỗi `intervalMs` khi `active`; dừng hẳn khi
 * unmount hoặc tab ẩn để không bắn request vô ích. Request đang bay bị abort.
 */
export function usePolling(task: (signal: AbortSignal) => Promise<void>, intervalMs: number, active: boolean, key?: unknown): void {
  const latest = useRef(task);
  const interval = useRef(intervalMs);
  useEffect(() => {
    latest.current = task;
  }, [task]);
  // Đổi nhịp không khởi động lại vòng poll (không hỏi thêm một lần ngay); nhịp mới áp từ lần hẹn kế tiếp.
  useEffect(() => {
    interval.current = intervalMs;
  }, [intervalMs]);

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
      if (!stopped) timer = setTimeout(tick, interval.current);
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
  }, [active, key]);
}
