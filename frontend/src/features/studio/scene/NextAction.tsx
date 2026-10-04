"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/studio/primitives";
import { ErrorFeedback } from "@/components/studio/feedback";
import { getJobScene, getReviewState, getSimulationPackage, type ReviewStateView, type SimulationPackageView } from "@/lib/api/studio";
import { usePolling } from "@/features/studio/usePolling";
import { useAuth } from "@/features/studio/AuthProvider";
import { isReviewer } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { errorMessage } from "@/lib/ui-error";
import type { SceneIR } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";
import { isJobStale, useNow, type Tab, type StudioMode } from "@/features/studio/scene/state";

interface Detail { scene: SceneIR; pkg: SimulationPackageView | null; review: ReviewStateView | null }
/** Bước tiếp theo đọc published state; không tạo lifecycle cạnh tranh với backend. */
export function NextAction({ jobId, progress, current, mode, sceneReady, revision, busy, onOpen, onRetry }: {
  jobId: string; progress: JobProgress | null; current: Tab; mode: StudioMode; sceneReady: boolean; revision: string | null;
  busy: boolean; onOpen: (tab: Tab, mode?: StudioMode) => void; onRetry: () => void;
}) {
  const { me } = useAuth();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const now = useNow(progress?.status === "RUNNING");
  const stale = isJobStale(progress, now);
  const load = useCallback(async (signal: AbortSignal) => {
    const scene = await getJobScene(jobId, signal);
    if (signal.aborted) return;
    if (!scene.ok) { setError(errorMessage(scene.error)); setDetail(null); return; }
    const values = await Promise.allSettled([getSimulationPackage(jobId, signal), getReviewState(jobId, signal)]);
    if (signal.aborted) return;
    const missing = values.find((value) => value.status === "rejected" && !(value.reason instanceof ApiError && value.reason.status === 404));
    if (missing?.status === "rejected") { setError(errorMessage(missing.reason)); setDetail(null); return; }
    setError(null);
    setDetail({ scene: scene.data.scene, pkg: values[0].status === "fulfilled" ? values[0].value : null, review: values[1].status === "fulfilled" ? values[1].value : null });
  }, [jobId]);
  useEffect(() => {
    if (!sceneReady || revision === null) return;
    const controller = new AbortController();
    const timer = setTimeout(() => void load(controller.signal), 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [revision, sceneReady, load]);
  usePolling(load, 10000, sceneReady);
  if (!progress) return null;
  let title: string | null = null;
  let description: string | null = null;
  let action: { label: string; tab: Tab; mode?: StudioMode } | null = null;
  if (stale) {
    title = "Tiến trình bị gián đoạn";
    description = "Bấm thử lại để tiếp tục huấn luyện từ checkpoint đã lưu.";
  } else if (progress.status === "FAILED") {
    // Không hiển thị "Xử lý chưa hoàn tất. Xem nguyên nhân..." - các thông tin lỗi đã có ở stage trong Timeline
  } else if (progress.status === "CANCELLED") {
    title = "Đã huỷ xử lý";
    description = "Kết quả đã publish vẫn được giữ; mở giai đoạn hoàn tất để xem.";
  } else if (progress.waiting_for === "resources") {
    title = "Đang chờ tài nguyên";
    description = "Giữ nguyên cấu hình đã chọn. Máy xử lý kiểm tra lại và tự chạy tiếp khi đủ tài nguyên; có thể rời trang hoặc huỷ job.";
  } else if (progress.waiting_for === "metric_confirmation") {
    title = "Cần bạn xác nhận tỉ lệ mét";
    description = "Chọn điểm và nhập kích thước thật để pipeline tiếp tục.";
    action = { label: "Xác nhận tỉ lệ mét", tab: "studio", mode: "metric" };
  } else if (progress.status === "QUEUED") {
    title = "Đang chờ worker";
    description = "Job đã vào hàng đợi. Theo dõi các giai đoạn bên dưới.";
  } else if (sceneReady) {
    title = "Đang đọc bước tiếp theo";
    description = "Đối chiếu vật thể, gói và trạng thái duyệt của revision hiện tại.";
    if (detail && (revision === null || detail.scene.scene_revision === revision)) {
      // Ứng viên do pipeline tạo có `active=false` cho tới khi được xác nhận, nên đếm theo trạng thái (cùng quy tắc
      // với bộ lọc "Chờ xác nhận" của Studio), không theo cờ `active`.
      const review_of = (object: SceneIR["objects"][number]) => object.provenance.review;
      const pending = detail.scene.objects.filter((object) => object.state === "CANDIDATE" && review_of(object) !== "IGNORED" && review_of(object) !== "DELETED").length;
      const awaitingChoice = detail.scene.provenance.object_extraction === "objectify_failed_awaiting_choice";
      const pkg = detail.pkg?.scene_revision === detail.scene.scene_revision ? detail.pkg : null;
      const review = detail.review?.record.scene_revision === detail.scene.scene_revision ? detail.review : null;
      if (awaitingChoice) {
        // Pipeline v2: tách theo vật lỗi hết số lần thử; scene chỉ có môi trường cho tới khi người dùng chọn.
        title = "Tách theo vật chưa thành công";
        description = "Chọn chạy lại tách theo vật hoặc dùng hộp ứng viên trong Studio.";
        action = { label: "Mở Studio để chọn", tab: "studio", mode: "scene" };
      } else if (pending) {
        title = "Cần xác nhận vật thể";
        description = String(pending) + " ứng viên chưa được xác nhận.";
        action = { label: "Xác nhận vật thể", tab: "studio", mode: "scene" };
      } else if (review?.record.status === "RELEASED" && review.release && review.release_archive) {
        title = "Đã có bản phát hành"; description = "Tải đúng gói đã được kiểm tra và duyệt."; action = { label: "Xem kết quả", tab: "results" };
      } else if (review?.record.status === "READY_FOR_REVIEW") {
        title = "Đạt kiểm tra — chờ duyệt"; description = isReviewer(me) ? "Kiểm tra bằng chứng trước khi quyết định." : "Reviewer sẽ quyết định trên đúng gói của revision này."; action = { label: "Xem kiểm tra & duyệt", tab: "review" };
      } else if (pkg?.package_ref) {
        title = "Đã có gói mô phỏng"; description = review?.blockers[0] ?? "Gói candidate có thể tải; bản phát hành cần validation và Reviewer duyệt."; action = { label: "Xem kiểm tra & duyệt", tab: "review" };
      } else {
        title = pkg?.preflight.blocking_result === "FAIL" ? "Cần sửa theo preflight" : "Sẵn sàng tạo gói";
        description = "Tạo gói và đọc preflight ở Kiểm tra & duyệt."; action = { label: "Mở tạo gói mô phỏng", tab: "review" };
      }
    }
  }
  const atTarget = action && current === action.tab && (!action.mode || mode === action.mode);
  const showRetry = Boolean(stale || (progress.status === "FAILED" && progress.error?.retryable));
  if (!title && !showRetry && !(sceneReady && error)) return null;
  return <section aria-label="Bước tiếp theo" className="border-b border-line bg-paper px-4 py-3 sm:px-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      {title && <div className="min-w-0"><p className="text-sm font-bold">{title}</p>{description && <p className="mt-0.5 text-sm text-ink-muted">{description}</p>}</div>}
      {showRetry && <Button size="sm" disabled={busy} onClick={onRetry}>Thử lại</Button>}
      {action && !atTarget && <Button size="sm" onClick={() => onOpen(action!.tab, action!.mode)}>{action.label}</Button>}
    </div>
    {sceneReady && error && <ErrorFeedback message={error} className="mt-2" retry={() => void load(new AbortController().signal)} />}
  </section>;
}
