"use client";

import { useEffect, useState } from "react";

import { OperatorClock } from "@/features/studio/value/operator-clock";
import { postOperatorTime, type OperatorTimeBatch, type OperatorTimeSurface } from "@/lib/api/value";

const TICK_MS = 1_000;
/** Các sự kiện được coi là thao tác của người dùng; `pointermove` chỉ tính khi đang giữ nút. */
const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel"] as const;

function newSessionKey(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  return Array.from({ length: 4 }, () => Math.random().toString(16).slice(2, 10)).join("");
}

/**
 * Đếm phút công người trên một tab của trang scene. Chỉ chạy khi `enabled` (người xem có quyền sửa job).
 * Đổi tab, tab ẩn, rời trang đều đóng lô hiện tại trước, để lô của tab cũ không bị gắn sang tab mới.
 */
export function useOperatorTime({
  jobId,
  surface,
  enabled,
}: {
  jobId: string;
  surface: OperatorTimeSurface;
  enabled: boolean;
}): void {
  const [sessionKey] = useState(newSessionKey);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const clock = new OperatorClock(sessionKey, surface);
    const send = (batch: OperatorTimeBatch | null) => {
      if (batch) void postOperatorTime(jobId, batch, { keepalive: true });
    };
    const isVisible = () => document.visibilityState === "visible";

    const pause = () => send(clock.close(Date.now()));
    const resume = () => {
      if (isVisible() && !clock.running) clock.start(Date.now());
    };
    const onActivity = () => clock.activity(Date.now());
    const onPointerMove = (event: PointerEvent) => {
      if (event.buttons !== 0) clock.activity(Date.now());
    };
    const onVisibility = () => (isVisible() ? resume() : pause());

    resume();
    const timer = window.setInterval(() => {
      const now = Date.now();
      if (!clock.running) return;
      clock.tick(now);
      if (clock.due(now)) send(clock.cut(now));
    }, TICK_MS);
    for (const name of ACTIVITY_EVENTS) window.addEventListener(name, onActivity, { passive: true });
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", pause);

    return () => {
      window.clearInterval(timer);
      for (const name of ACTIVITY_EVENTS) window.removeEventListener(name, onActivity);
      window.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", pause);
      pause();
    };
  }, [enabled, jobId, sessionKey, surface]);
}
