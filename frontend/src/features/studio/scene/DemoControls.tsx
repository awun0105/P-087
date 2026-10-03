"use client";

import { Bookmark, BookmarkX, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { notifySuccess } from "@/components/studio/feedback";
import { Badge, Button } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { isReviewer } from "@/lib/api/auth";
import { clearDemo, getDemoState, markDemo, resetDemo } from "@/lib/api/studio";
import type { DemoState } from "@/lib/contracts/studio";
import { errorMessage } from "@/lib/ui-error";

/**
 * Bản demo của scene (header): huy hiệu, nút Khôi phục bản demo, và với Reviewer là nút đánh dấu/bỏ đánh dấu.
 *
 * Khôi phục chỉ đưa nội dung scene về mốc gốc bằng một revision mới (lịch sử còn nguyên) — không chạy lại bước xử lý
 * nào. `revision` là revision mới nhất màn hình biết; đổi thì đọc lại trạng thái để biết scene còn đúng mốc không.
 */
export function DemoControls({
  jobId,
  revision,
  sceneReady,
  onRestored,
}: {
  jobId: string;
  revision: string | null;
  sceneReady: boolean;
  /** Revision mới sau khi khôi phục; màn Studio dùng để tải lại scene. */
  onRestored: (revision: string) => void;
}) {
  const { me } = useAuth();
  const reviewer = isReviewer(me);
  const [state, setState] = useState<DemoState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sceneReady) return;
    const controller = new AbortController();
    getDemoState(jobId, controller.signal).then(
      (next) => { if (!controller.signal.aborted) setState(next); },
      () => { /* Không đọc được trạng thái demo không chặn màn scene; chỉ ẩn điều khiển. */ },
    );
    return () => controller.abort();
  }, [jobId, revision, sceneReady]);

  const run = useCallback(async (action: () => Promise<DemoState>, success: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setState(next);
      notifySuccess(success);
      return next;
    } catch (cause) {
      setError(errorMessage(cause, "Thao tác bản demo thất bại"));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  if (!sceneReady || !state) return null;
  const baseline = state.baseline;
  // Scene thường và người xem không phải Reviewer: không có gì về bản demo để hiện.
  if (!baseline && !reviewer) return null;
  async function restore() {
    if (!state?.current_revision) return;
    if (!window.confirm("Đưa scene về bản demo gốc? Mọi chỉnh sửa sau mốc gốc vẫn nằm trong lịch sử revision; không bước xử lý nào chạy lại.")) return;
    const next = await run(() => resetDemo(jobId, state.current_revision!), "Đã khôi phục bản demo gốc.");
    if (next?.current_revision) onRestored(next.current_revision);
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      {baseline && <Badge tone="ember" title={`Mốc gốc: ${baseline.scene_revision}`}>Bản demo</Badge>}
      {baseline && (
        <Button size="sm" variant="secondary" disabled={busy || state.at_baseline} onClick={() => void restore()}
          title={state.at_baseline ? "Scene đang đúng bản demo gốc." : "Đưa scene về đúng lúc được đánh dấu làm bản demo."}>
          <RotateCcw aria-hidden />
          {state.at_baseline ? "Đang ở bản gốc" : "Khôi phục bản demo"}
        </Button>
      )}
      {reviewer && !baseline && (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => markDemo(jobId), "Đã đánh dấu scene làm bản demo.")}
          title="Lấy trạng thái hiện tại của scene làm bản demo gốc để khôi phục về sau.">
          <Bookmark aria-hidden />
          Đặt làm bản demo
        </Button>
      )}
      {reviewer && baseline && (
        <Button size="sm" variant="ghost" disabled={busy}
          onClick={() => { if (window.confirm("Bỏ đánh dấu bản demo? Nội dung scene giữ nguyên.")) void run(() => clearDemo(jobId), "Đã bỏ đánh dấu bản demo."); }}>
          <BookmarkX aria-hidden />
          Bỏ đánh dấu
        </Button>
      )}
      {error && <span role="alert" className="text-xs text-rust">{error}</span>}
    </div>
  );
}
