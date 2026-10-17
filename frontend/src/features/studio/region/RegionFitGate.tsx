"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/studio/primitives";
import { ApiError } from "@/lib/api/client";
import { fetchRegionFit, type RegionFit } from "@/lib/api/studio";
import type { SceneObject } from "@/lib/contracts/api";

/**
 * Cổng mở "Chỉnh vùng" (T-023): lấy box ban đầu từ máy chủ trước khi có phiên. Đang chờ thì không có Apply, lỗi thì
 * không tạo box mặc định từ kích thước; người dùng chỉ có Thử lại hoặc Đóng.
 */
export function RegionFitGate({
  jobId,
  object,
  sceneRevision,
  onReady,
  onClose,
}: {
  jobId: string;
  object: SceneObject;
  sceneRevision: string;
  onReady(fit: RegionFit): void;
  onClose(): void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // Callback đổi mỗi lần cha render; giữ bản mới trong ref để effect chỉ chạy lại khi vật, revision hoặc lần thử đổi.
  const latestReady = useRef(onReady);
  useEffect(() => {
    latestReady.current = onReady;
  });

  useEffect(() => {
    const controller = new AbortController();
    fetchRegionFit(jobId, object.id, sceneRevision, controller.signal)
      .then((fit) => {
        if (!controller.signal.aborted) latestReady.current(fit);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof ApiError ? cause.detail : "Không lấy được vùng hiện tại của vật.");
      });
    return () => controller.abort();
  }, [jobId, object.id, sceneRevision, attempt]);

  return (
    <section
      aria-label="Chỉnh vùng đang tải"
      className="pointer-events-auto w-80 max-w-full space-y-3 rounded-md border border-line-dark bg-viewport-deep/95 p-3 text-xs text-on-dark shadow-2xl backdrop-blur-md"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 className="truncate text-sm font-semibold">Chỉnh vùng · {object.name}</h3>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Đóng
        </Button>
      </header>
      {error === null ? (
        <p role="status" className="flex items-center gap-2 text-on-dark/70">
          <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> Đang lấy vùng hiện tại…
        </p>
      ) : (
        <div role="alert" className="space-y-2">
          <p>{error}</p>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setError(null);
              setAttempt((value) => value + 1);
            }}
          >
            Thử lại
          </Button>
        </div>
      )}
    </section>
  );
}
