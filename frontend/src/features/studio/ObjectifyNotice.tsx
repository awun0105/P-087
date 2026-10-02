"use client";

import { Boxes, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button, Notice } from "@/components/studio/primitives";
import { ApiError } from "@/lib/api/client";
import { getObjectifyState, requestObjectify, type ObjectifyMode, type ObjectifyState } from "@/lib/api/studio";

const POLL_MS = 5000;

/**
 * Báo scene chưa phải scene theo vật và cho người dùng chọn: chạy lại tách theo vật, hoặc dùng hộp ứng viên.
 * Việc nặng do worker làm; component chỉ gửi yêu cầu, hỏi trạng thái định kỳ và báo khi có revision mới.
 */
export function ObjectifyNotice({ jobId, revision, onRevision }: { jobId: string; revision: string; onRevision: () => void }) {
  const [state, setState] = useState<ObjectifyState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [tick, setTick] = useState(0);
  // Chỉ báo lên một lần cho mỗi revision kết quả, kể cả khi poll trả "done" nhiều lần.
  const announced = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getObjectifyState(jobId, controller.signal).then(
      (next) => {
        setState(next);
        if (next.status === "done" && next.result_revision && next.result_revision !== revision && announced.current !== next.result_revision) {
          announced.current = next.result_revision;
          onRevision();
        }
      },
      () => undefined, // route chưa có (API cũ) hoặc scene chưa sẵn sàng: không hiện gì
    );
    return () => controller.abort();
  }, [jobId, revision, tick]); // eslint-disable-line react-hooks/exhaustive-deps -- onRevision chỉ là kênh báo lên

  const pending = state?.status === "queued" || state?.status === "running";
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), POLL_MS);
    return () => window.clearInterval(timer);
  }, [pending]);

  if (!state) return null;
  const send = async (mode: ObjectifyMode) => {
    if (mode === "objectify" && !state.awaiting_choice && !window.confirm("Chạy lại tách theo vật sẽ thay toàn bộ vật hiện có bằng tập ứng viên mới (hoàn tác được). Tiếp tục?")) return;
    setSending(true);
    setError(null);
    try {
      setState(await requestObjectify(jobId, revision, mode));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : "Không gửi được yêu cầu.");
    } finally {
      setSending(false);
    }
  };

  if (pending) {
    return (
      <Notice tone="ember" className="m-3" icon={<Loader2 className="size-4 animate-spin" aria-hidden />}>
        {state.mode === "boxes" ? "Đang dựng hộp ứng viên…" : "Đang chạy lại tách theo vật (tự thử lại tối đa 3 lần, mỗi lần vài phút)…"}
        {state.status === "queued" && " Đang chờ máy xử lý rảnh."}
      </Notice>
    );
  }
  if (state.object_centric) return null;

  const failed = state.status === "failed";
  const actions = (
    <span className="mt-2 flex flex-wrap gap-2">
      {state.available && (
        <Button size="sm" variant="secondary" disabled={sending} onClick={() => void send("objectify")}>
          <RefreshCw aria-hidden /> Chạy lại tách theo vật
        </Button>
      )}
      {(state.awaiting_choice || failed) && (
        <Button size="sm" variant="ghost" disabled={sending} onClick={() => void send("boxes")}>
          <Boxes aria-hidden /> Dùng hộp ứng viên
        </Button>
      )}
    </span>
  );
  if (!state.awaiting_choice && !failed && !state.available) return null;
  return (
    <Notice tone={state.awaiting_choice || failed ? "rust" : "ochre"} className="m-3">
      {state.awaiting_choice || failed ? (
        <>
          <strong className="font-medium">Tách theo vật không thành công sau 3 lần thử.</strong> Scene hiện chỉ có môi trường. Bạn có thể chạy lại, hoặc
          dùng hộp ứng viên (mỗi vật là một hộp đánh dấu vị trí, hình 3DGS không tách rời theo vật).
        </>
      ) : (
        <>Scene này đang dùng hộp ứng viên: hình 3DGS chưa tách theo từng vật nên kéo vật đi hình không đi theo.</>
      )}
      {(state.error ?? state.note) && <span className="mt-1 block text-xs opacity-80">Chi tiết: {state.error ?? state.note}</span>}
      {error && <span className="mt-1 block text-xs">{error}</span>}
      {actions}
    </Notice>
  );
}
