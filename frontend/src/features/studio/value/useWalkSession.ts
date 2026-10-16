"use client";

import { useContext, useEffect } from "react";

import { ValueTrackingContext } from "@/features/studio/value/tracking-context";
import { postWalkSession } from "@/lib/api/value";

/** Walk dưới 5 giây không được tính là hoàn tất (architecture §15.3 quy tắc 5). */
const COMPLETED_MIN_MS = 5_000;
/** Giới hạn cứng của một phiên theo máy chủ. */
const MAX_SESSION_MS = 2 * 60 * 60 * 1000;

/**
 * Ghi một phiên Walk: bắt đầu khi bật, gửi khi tắt, khi đổi revision, khi rời tab Studio hoặc rời trang.
 * Không ghi gì khi người xem không được sửa job, khi chưa có revision, hoặc khi phiên không có độ dài.
 */
export function useWalkSession({ walking, sceneRevision }: { walking: boolean; sceneRevision: string | undefined }): void {
  const tracking = useContext(ValueTrackingContext);

  useEffect(() => {
    if (!tracking.enabled || !walking || !sceneRevision) return;
    const startedMs = Date.now();
    return () => {
      const endedMs = Math.min(Date.now(), startedMs + MAX_SESSION_MS);
      if (endedMs <= startedMs) return;
      void postWalkSession(
        tracking.jobId,
        {
          scene_revision: sceneRevision,
          started_at: new Date(startedMs).toISOString(),
          ended_at: new Date(endedMs).toISOString(),
          outcome: endedMs - startedMs >= COMPLETED_MIN_MS ? "completed" : "aborted",
        },
        { keepalive: true },
      );
    };
  }, [tracking.enabled, tracking.jobId, walking, sceneRevision]);
}
