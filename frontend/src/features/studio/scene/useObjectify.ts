"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  buildObjectGeometry,
  cancelObjectify,
  getObjectifyState,
  requestObjectify,
  type ObjectifyMode,
  type ObjectifyState,
} from "@/lib/api/studio";
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
  external,
  onRefresh,
}: {
  jobId: string;
  /** Revision đang hiển thị; bỏ trống thì dùng revision hiện tại mà máy chủ báo trong trạng thái. */
  revision?: string | null;
  enabled?: boolean;
  /** Có revision mới do yêu cầu dựng lại tạo ra (kể cả khi chính hook này vừa theo dõi yêu cầu chạy xong). */
  onRevision?: (revision: string) => void;
  /** T-060: trạng thái lấy từ `/pipeline` của trang; khi có thì hook không tự đọc / tự poll. */
  external?: ObjectifyState | null;
  /** Đọc lại ngay qua nguồn chung (pipeline) thay vì tự gọi API. */
  onRefresh?: () => void;
}) {
  const shared = external !== undefined;
  const [state, setState] = useState<ObjectifyState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [tick, setTick] = useState(0);
  // Chỉ báo lên một lần cho mỗi revision kết quả, kể cả khi poll trả "done" nhiều lần.
  const announced = useRef<string | null>(null);
  // Đã thấy yêu cầu xếp hàng/đang chạy: khi nó xong thì revision hiện tại chính là kết quả nên không so với "revision đang
  // hiển thị" được nữa, phải báo theo việc chuyển trạng thái.
  const sawPending = useRef(false);

  const observe = useCallback((next: ObjectifyState) => {
    setState(next);
    const shown = revision ?? next.scene_revision;
    if (next.status === "queued" || next.status === "running") sawPending.current = true;
    const fresh = next.result_revision !== shown || sawPending.current;
    if (next.status === "done" && next.result_revision && fresh && announced.current !== next.result_revision) {
      announced.current = next.result_revision;
      sawPending.current = false;
      onRevision?.(next.result_revision);
    }
  }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps -- onRevision chỉ là kênh báo lên

  // Nguồn chung (pipeline): chỉ áp khi trang có trạng thái mới, không tự gọi API.
  useEffect(() => {
    if (!shared || !external) return;
    const timer = setTimeout(() => observe(external), 0);
    return () => clearTimeout(timer);
  }, [shared, external, observe]);

  useEffect(() => {
    if (!enabled || shared) return;
    const controller = new AbortController();
    getObjectifyState(jobId, controller.signal).then(
      observe,
      () => undefined, // route chưa có (API cũ) hoặc scene chưa sẵn sàng: không hiện gì
    );
    return () => controller.abort();
  }, [jobId, enabled, shared, tick, observe]);

  const pending = state?.status === "queued" || state?.status === "running";
  // Trạng thái chờ có thể đến từ phản hồi của chính lệnh gửi (không qua lần đọc), nên ghi nhận ở đây.
  useEffect(() => {
    if (pending) sawPending.current = true;
  }, [pending]);
  useEffect(() => {
    if (!enabled || !pending || shared) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, pending, shared]);

  const send = useCallback(async (mode: ObjectifyMode, expectedRevision?: string) => {
    const expected = expectedRevision ?? revision ?? state?.scene_revision;
    if (!expected) {
      setError("Chưa biết revision hiện tại của scene. Tải lại trang rồi thử lại.");
      return;
    }
    setSending(true);
    setError(null);
    try {
      // Tạo mesh đi qua route riêng; các chế độ tách còn lại đi qua hàng đợi objectify.
      setState(await (mode === "geometry" ? buildObjectGeometry(jobId, expected) : requestObjectify(jobId, expected, mode)));
      onRefresh?.();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : "Không gửi được yêu cầu.");
      // 409: scene đã đổi (revision cũ) hoặc đã có yêu cầu khác; đọc lại trạng thái để màn hình khớp máy chủ.
      if (cause instanceof ApiError && cause.status === 409) {
        if (onRefresh) onRefresh();
        else setTick((value) => value + 1);
      }
    } finally {
      setSending(false);
    }
  }, [jobId, revision, state?.scene_revision, onRefresh]);

  // Huỷ đúng yêu cầu đang hiển thị (operation_id); không có thì huỷ theo job như trước.
  const operationId = state?.operation_id;
  const cancel = useCallback(async () => {
    setSending(true);
    setError(null);
    try {
      setState(await (operationId ? cancelObjectify(jobId, operationId) : cancelObjectify(jobId)));
      onRefresh?.();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : "Không hủy được yêu cầu.");
    } finally {
      setSending(false);
    }
  }, [jobId, operationId, onRefresh]);

  // Đọc lại trạng thái ngay, cho thao tác không đi qua `send` (ví dụ áp vùng nhận 202).
  const refresh = useCallback(() => {
    if (onRefresh) onRefresh();
    else setTick((value) => value + 1);
  }, [onRefresh]);

  // Giá trị ổn định: consumer của context chỉ render lại khi trạng thái thật sự đổi (T-060).
  return useMemo(
    () => ({ state, error, sending, pending, send, cancel, refresh }),
    [state, error, sending, pending, send, cancel, refresh],
  );
}

/** Các chế độ là việc dựng hình học, hiện ở hàng "Duyệt vật & Tạo mesh" (T-021). */
const BUILD_MODES: readonly ObjectifyMode[] = ["geometry", "region", "membership"];

/**
 * Hàng ảo "Duyệt vật & Tạo mesh" (T-021): không có trong contracts/StageId, chỉ tồn tại ở giao diện. Trạng thái lấy từ
 * `ObjectifyState` đã được chia sẻ. `null` khi scene không có khoá `object_geometry` (luồng cũ, không có hàng).
 */
export interface GeometryStep {
  state: StageState;
  /** Phase máy chủ đang chạy (shell, collider, ...); null khi đang xếp hàng hoặc chưa có. */
  phase: string | null;
  /** Lý do lỗi của lần yêu cầu gần nhất do máy chủ viết. */
  error: string | null;
  mode: ObjectifyMode | null;
  /** Máy chủ đã nhận lệnh huỷ và đang dừng worker. */
  cancelling: boolean;
  /** Việc dựng đang xếp hàng hoặc chạy: có thể huỷ. */
  busy: boolean;
  /** Dựng lại vùng thất bại trên scene đã Ready: scene vẫn giữ bản trước. */
  rebuildFailed: boolean;
}

/** Quy tắc trạng thái của hàng "Duyệt vật & Tạo mesh"; mỗi nhánh có một test trong `geometry-review-step.test.tsx`. */
export function geometryReviewStep(state: ObjectifyState | null): GeometryStep | null {
  if (!state || !state.object_geometry) return null;
  const base = {
    phase: state.phase ?? null,
    error: state.error ?? null,
    mode: state.mode,
    cancelling: state.cancellation_requested,
    busy: false,
    rebuildFailed: false,
  };
  if ((state.status === "queued" || state.status === "running") && state.mode && BUILD_MODES.includes(state.mode)) {
    return { ...base, state: "running", busy: true };
  }
  const failed = state.status === "failed" || state.status === "cancelled";
  if (state.object_geometry === "awaiting_review") {
    // Lỗi của revision khác không còn là lỗi của scene hiện tại: chỉ nêu khi cùng revision.
    const sameRevision = state.base_revision !== null && state.base_revision === state.scene_revision;
    if (failed && state.mode === "geometry" && sameRevision) return { ...base, state: "failed" };
    return { ...base, state: "waiting" };
  }
  // Lỗi dựng lại vùng chỉ nêu cho đúng revision đã gửi yêu cầu; sau một lần sửa khác thì scene đã đổi, không nêu nữa.
  if (failed && (state.mode === "region" || state.mode === "membership")) {
    const sameRevision = state.base_revision !== null && state.base_revision === state.scene_revision;
    return { ...base, state: "succeeded", rebuildFailed: sameRevision };
  }
  return { ...base, state: "succeeded" };
}

/**
 * Bước "Tách vật thể" của pipeline luôn ghi "thành công" vì scene đã được tạo, kể cả khi tách theo vật lỗi hết số lần
 * thử và scene chỉ có môi trường chờ người dùng chọn. Hàm này cho biết hàng bước đó phải hiện thế nào thay cho "đã xong":
 * đang chạy lại, hoặc lỗi kèm lý do. `null` = giữ nguyên trạng thái từ pipeline.
 */
export function objectifyStageOverride(state: ObjectifyState | null): { state: StageState; error?: ExecutionError } | null {
  if (!state) return null;
  // Chỉ việc tách mới làm hàng này chạy lại; việc dựng hình học (geometry/region/membership) hiện ở hàng "Duyệt vật & Tạo mesh".
  if ((state.status === "queued" || state.status === "running") && (state.mode === "objectify" || state.mode === "boxes")) {
    return { state: "running" };
  }
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
