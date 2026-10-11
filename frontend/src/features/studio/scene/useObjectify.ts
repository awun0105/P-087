"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { cancelObjectify, getObjectifyState, requestObjectify, type ObjectifyMode, type ObjectifyState } from "@/lib/api/studio";
import type { ExecutionError } from "@/lib/contracts/api";
import type { StageState } from "@/lib/contracts/studio";

const POLL_MS = 5000;

/**
 * Trạng thái "tách scene theo vật" của một scene và các thao tác chạy lại / dùng hộp ứng viên / hủy.
 *
 * Việc nặng do worker làm; hook chỉ gửi yêu cầu, hỏi trạng thái định kỳ khi còn xếp hàng hay đang chạy, và báo khi có
 * revision mới. Trang scene gọi hook này một lần và chia sẻ qua `ObjectifyContext` (xem `objectifyContext.tsx`) để thông
 * báo trong Studio, hàng bước "Tách vật thể" ở tab Tiến trình, chuông và trạng thái đầu trang luôn cùng một trạng thái.
 */
export function useObjectifyState({
  jobId,
  revision,
  enabled = true,
  onRevision,
}: {
  jobId: string;
  /** Revision đang hiển thị; bỏ trống thì dùng revision hiện tại mà máy chủ báo trong trạng thái. */
  revision?: string | null;
  enabled?: boolean;
  /** Có revision mới do yêu cầu dựng lại tạo ra (kể cả khi chính hook này vừa theo dõi yêu cầu chạy xong). */
  onRevision?: (revision: string) => void;
}) {
  const [state, setState] = useState<ObjectifyState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [tick, setTick] = useState(0);
  // Chỉ báo lên một lần cho mỗi revision kết quả, kể cả khi poll trả "done" nhiều lần.
  const announced = useRef<string | null>(null);
  // Đã thấy yêu cầu xếp hàng/đang chạy: khi nó xong thì revision hiện tại chính là kết quả nên không so với "revision đang
  // hiển thị" được nữa, phải báo theo việc chuyển trạng thái.
  const sawPending = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    getObjectifyState(jobId, controller.signal).then(
      (next) => {
        setState(next);
        const shown = revision ?? next.scene_revision;
        if (next.status === "queued" || next.status === "running") sawPending.current = true;
        const fresh = next.result_revision !== shown || sawPending.current;
        if (next.status === "done" && next.result_revision && fresh && announced.current !== next.result_revision) {
          announced.current = next.result_revision;
          sawPending.current = false;
          onRevision?.(next.result_revision);
        }
      },
      () => undefined, // route chưa có (API cũ) hoặc scene chưa sẵn sàng: không hiện gì
    );
    return () => controller.abort();
  }, [jobId, revision, enabled, tick]); // eslint-disable-line react-hooks/exhaustive-deps -- onRevision chỉ là kênh báo lên

  const pending = state?.status === "queued" || state?.status === "running";
  // Trạng thái chờ có thể đến từ phản hồi của chính lệnh gửi (không qua lần đọc), nên ghi nhận ở đây.
  useEffect(() => {
    if (pending) sawPending.current = true;
  }, [pending]);
  useEffect(() => {
    if (!enabled || !pending) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, pending]);

  const send = useCallback(async (mode: ObjectifyMode, expectedRevision?: string) => {
    const expected = expectedRevision ?? revision ?? state?.scene_revision;
    if (!expected) {
      setError("Chưa biết revision hiện tại của scene. Tải lại trang rồi thử lại.");
      return;
    }
    setSending(true);
    setError(null);
    try {
      setState(await requestObjectify(jobId, expected, mode));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : "Không gửi được yêu cầu.");
      // 409: scene đã đổi (revision cũ) hoặc đã có yêu cầu khác; đọc lại trạng thái để màn hình khớp máy chủ.
      if (cause instanceof ApiError && cause.status === 409) setTick((value) => value + 1);
    } finally {
      setSending(false);
    }
  }, [jobId, revision, state?.scene_revision]);

  const cancel = useCallback(async () => {
    setSending(true);
    setError(null);
    try {
      setState(await cancelObjectify(jobId));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : "Không hủy được yêu cầu.");
    } finally {
      setSending(false);
    }
  }, [jobId]);

  return { state, error, sending, pending, send, cancel };
}

/**
 * Bước "Tách vật thể" của pipeline luôn ghi "thành công" vì scene đã được tạo, kể cả khi tách theo vật lỗi hết số lần
 * thử và scene chỉ có môi trường chờ người dùng chọn. Hàm này cho biết hàng bước đó phải hiện thế nào thay cho "đã xong":
 * đang chạy lại, hoặc lỗi kèm lý do. `null` = giữ nguyên trạng thái từ pipeline.
 */
export function objectifyStageOverride(state: ObjectifyState | null): { state: StageState; error?: ExecutionError } | null {
  if (!state) return null;
  if (state.status === "queued" || state.status === "running") return { state: "running" };
  // Chỉ báo lỗi bước khi scene thật sự không có vật nào (tách lỗi hết số lần thử). Dựng lại lỗi mà scene vẫn có vật
  // (tách theo vật hay hộp ứng viên) thì bước vẫn đã xong; chi tiết lỗi lần dựng lại nằm ở thông báo trong Studio.
  if (state.awaiting_choice) {
    const detail = state.error ?? state.note;
    return {
      state: "failed",
      error: {
        stage_id: "ST-OBJECT-EXTRACT",
        error_code: "OBJECTIFY_FAILED",
        human_message: state.retryable === false
          ? "Tách theo vật bị dừng vì dữ liệu chưa đạt điều kiện. Scene hiện chỉ có môi trường; kiểm tra dữ liệu sàn hoặc dùng hộp ứng viên."
          : "Tách theo vật không thành công. Scene hiện chỉ có môi trường, chưa có vật nào; chạy lại hoặc dùng hộp ứng viên.",
        retryable: state.retryable !== false,
        details: detail ? { log_excerpt: [detail] } : null,
      },
    };
  }
  return null;
}
