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
 * revision mới. Dùng chung cho thông báo trong Studio (`ObjectifyNotice`) và hàng bước "Tách vật thể" ở tab Tiến trình.
 */
export function useObjectify({
  jobId,
  revision,
  enabled = true,
  onRevision,
}: {
  jobId: string;
  /** Revision đang hiển thị; bỏ trống thì dùng revision hiện tại mà máy chủ báo trong trạng thái. */
  revision?: string | null;
  enabled?: boolean;
  /** Có revision mới do yêu cầu dựng lại tạo ra. */
  onRevision?: () => void;
}) {
  const [state, setState] = useState<ObjectifyState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [tick, setTick] = useState(0);
  // Chỉ báo lên một lần cho mỗi revision kết quả, kể cả khi poll trả "done" nhiều lần.
  const announced = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    getObjectifyState(jobId, controller.signal).then(
      (next) => {
        setState(next);
        const shown = revision ?? next.scene_revision;
        if (next.status === "done" && next.result_revision && next.result_revision !== shown && announced.current !== next.result_revision) {
          announced.current = next.result_revision;
          onRevision?.();
        }
      },
      () => undefined, // route chưa có (API cũ) hoặc scene chưa sẵn sàng: không hiện gì
    );
    return () => controller.abort();
  }, [jobId, revision, enabled, tick]); // eslint-disable-line react-hooks/exhaustive-deps -- onRevision chỉ là kênh báo lên

  const pending = state?.status === "queued" || state?.status === "running";
  useEffect(() => {
    if (!enabled || !pending) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, pending]);

  const send = useCallback(async (mode: ObjectifyMode) => {
    const expected = revision ?? state?.scene_revision;
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
  // Dựng lại lỗi nhưng scene hiện tại vẫn là scene theo vật tốt thì không có gì để báo ở bước này.
  if (state.awaiting_choice || (state.status === "failed" && !state.object_centric)) {
    const detail = state.error ?? state.note;
    return {
      state: "failed",
      error: {
        stage_id: "ST-OBJECT-EXTRACT",
        error_code: "OBJECTIFY_FAILED",
        human_message: "Tách theo vật không thành công sau 3 lần thử. Scene hiện chỉ có môi trường, chưa có vật nào; chạy lại hoặc dùng hộp ứng viên.",
        retryable: true,
        details: detail ? { log_excerpt: [detail] } : null,
      },
    };
  }
  return null;
}
