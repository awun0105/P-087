"use client";

import { Boxes, Loader2, RefreshCw } from "lucide-react";

import { Button, Notice } from "@/components/studio/primitives";
import { useObjectify } from "@/features/studio/scene/objectifyContext";
import type { ObjectifyMode } from "@/lib/api/studio";

/**
 * Báo scene chưa phải scene theo vật và cho người dùng chọn: chạy lại tách theo vật, hoặc dùng hộp ứng viên.
 * Cùng trạng thái và thao tác với hàng bước "Tách vật thể" ở tab Tiến trình (xem `useObjectify`).
 */
export function ObjectifyNotice({ jobId, revision, onRevision }: { jobId: string; revision: string; onRevision: () => void }) {
  const { state, error, sending, send: sendRequest, cancel } = useObjectify({ jobId, revision, onRevision });

  if (!state) return null;
  const send = async (mode: ObjectifyMode) => {
    if (mode === "objectify" && !state.awaiting_choice && !window.confirm("Chạy lại tách theo vật sẽ thay toàn bộ vật hiện có bằng tập ứng viên mới (hoàn tác được). Tiếp tục?")) return;
    await sendRequest(mode, revision);
  };

  const pending = state.status === "queued" || state.status === "running";
  if (pending) {
    return (
      <Notice tone="ember" className="m-3" icon={<Loader2 className="size-4 animate-spin" aria-hidden />}>
        {state.cancellation_requested
          ? "Đang dừng tiến trình và giải phóng tài nguyên…"
          : state.mode === "membership"
            ? `Đang tái tạo sau hiệu chỉnh Gaussian · ${state.phase ?? state.status}. Scene hiện tại được giữ đến khi hoàn tất.`
          : state.mode === "boxes"
            ? "Đang dựng hộp ứng viên…"
            : "Đang chạy lại tách theo vật (tự thử lại tối đa 3 lần, mỗi lần vài phút)…"}
        {state.status === "queued" && !state.cancellation_requested && " Đang chờ máy xử lý rảnh."}
        {!state.cancellation_requested && (
          <span className="mt-2 block">
            <Button size="sm" variant="ghost" disabled={sending} onClick={() => void cancel()}>
              Hủy yêu cầu
            </Button>
          </span>
        )}
        {error && <span className="mt-1 block text-xs">{error}</span>}
      </Notice>
    );
  }
  if (state.mode === "membership") {
    return state.status === "failed" || state.status === "cancelled" ? (
      <Notice tone="rust" className="m-3">Tái tạo {state.status === "cancelled" ? "đã hủy" : "thất bại"}. Scene hiện tại được giữ nguyên. Mở chỉnh vùng Gaussian để thử lại. {state.error}</Notice>
    ) : null;
  }
  if (state.object_centric && state.status !== "cancelled") return null;

  const failed = state.status === "failed";
  const actions = (
    <span className="mt-2 flex flex-wrap gap-2">
      {state.available && state.retryable !== false && (
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
      {state.status === "cancelled" ? (
        <>Yêu cầu đã hủy. Scene vẫn giữ revision hiện tại.</>
      ) : state.awaiting_choice || failed ? (
        <>
          <strong className="font-medium">Tách theo vật không thành công.</strong>{" "}
          {state.retryable === false
            ? "Dữ liệu chưa đạt điều kiện; cần kiểm tra dữ liệu sàn hoặc dùng hộp ứng viên."
            : "Bạn có thể chạy lại hoặc dùng hộp ứng viên."}{" "}
          Hộp ứng viên đánh dấu vị trí vật; hình 3DGS chưa tách rời theo vật.
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
