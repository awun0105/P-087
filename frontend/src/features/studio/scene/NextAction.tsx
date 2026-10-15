import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, X } from "lucide-react";
import { Button } from "@/components/studio/primitives";
import { ErrorFeedback } from "@/components/studio/feedback";
import { getJobScene, getReviewState, getSimulationPackage, type ReviewStateView, type SimulationPackageView } from "@/lib/api/studio";
import { usePolling } from "@/features/studio/usePolling";
import { useAuth } from "@/features/studio/AuthProvider";
import { GuestQuotaStatus } from "@/features/studio/auth/GuestQuotaStatus";
import { isReviewer, resourceCapabilityAllowed } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { errorMessage } from "@/lib/ui-error";
import type { SceneIR } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";
import { isJobStale, useNow, type Tab, type StudioMode } from "@/features/studio/scene/state";
import { useObjectify } from "@/features/studio/scene/objectifyContext";
import { geometryReviewStep } from "@/features/studio/scene/useObjectify";
import { geometryPhaseLabel, objectGeometryState } from "@/lib/scene/geometry-state";
import { cn } from "@/lib/cn";

interface Detail { scene: SceneIR; pkg: SimulationPackageView | null; review: ReviewStateView | null }
/**
 * Bước tiếp theo đọc published state; không tạo lifecycle cạnh tranh với backend.
 *
 * Trang job dùng dạng `popover` (chuông ở header, chung cho mọi tab). Dạng `banner` chỉ còn để test đọc trực tiếp
 * tiêu đề/nút mà không phải mở chuông.
 */
export function NextAction({
  jobId,
  progress,
  current,
  mode,
  sceneReady,
  revision,
  busy,
  onOpen,
  onRetry,
  retryState,
  canMutateJob: suppliedCanMutateJob,
  canRetryJob: suppliedCanRetryJob,
  variant = "banner",
}: {
  jobId: string;
  progress: JobProgress | null;
  current: Tab;
  mode: StudioMode;
  sceneReady: boolean;
  revision: string | null;
  busy: boolean;
  onOpen: (tab: Tab, mode?: StudioMode) => void;
  onRetry: () => void;
  retryState?: "submitting" | "accepted" | "rejected" | "uncertain" | null;
  canMutateJob?: boolean;
  canRetryJob?: boolean;
  variant?: "banner" | "popover";
}) {
  const { me } = useAuth();
  const isGuest = me?.user?.role === "guest";
  const guestQuota = isGuest ? me.quota : null;
  const guestQuotaExhausted = guestQuota?.remaining === 0;
  const canMutateJob = suppliedCanMutateJob ?? resourceCapabilityAllowed(me, progress?.capabilities?.can_mutate);
  const canRetryJob = suppliedCanRetryJob ?? resourceCapabilityAllowed(me, progress?.capabilities?.can_retry);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleDown = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("mousedown", handleDown);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleDown);
      document.removeEventListener("keydown", handleKey);
    };
  }, [isOpen]);
  const now = useNow(progress?.status === "RUNNING");
  const stale = isJobStale(progress, now);
  // Việc tạo mesh / dựng lại vùng và trạng thái Draft (T-021): cùng nguồn với hàng "Duyệt vật & Tạo mesh".
  const objectify = useObjectify({ jobId });
  const geometry = geometryReviewStep(objectify.state);
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
  let pendingCount: number | null = null;
  // Đang đọc trạng thái chưa phải là thông báo cần người dùng chú ý: chuông không bật chấm cho nó.
  let reading = false;
  if (geometry?.state === "running") {
    const building = objectify.state?.mode === "geometry";
    title = building ? "Đang tạo mesh" : "Đang dựng lại vùng";
    description = (geometry.cancelling ? "Đang dừng…" : geometryPhaseLabel(geometry.phase)) ?? "Đang xếp hàng.";
    action = { label: "Xem tiến trình", tab: "progress" };
  } else if (retryState) {
    title = retryState === "submitting" ? "Đang gửi yêu cầu thử lại" : retryState === "rejected" ? "Đang kiểm tra phản hồi thử lại" : "Đang đồng bộ lần chạy mới";
    description = retryState === "uncertain"
      ? "Chưa xác nhận được máy chủ đã nhận yêu cầu. Trang đang đọc lại trạng thái job; nút thử lại tạm ẩn để tránh gửi trùng."
      : retryState === "accepted"
        ? "Máy chủ đã nhận yêu cầu. Nút thử lại chỉ hiện lại sau khi tiến trình xác nhận attempt mới hoặc lỗi từ chối rõ ràng."
        : "Đang tải lại trạng thái máy chủ trước khi mở lại thao tác.";
  } else if (stale) {
    title = "Worker chưa cập nhật tiến trình";
    description = "Backend vẫn ghi RUNNING nên chưa thể mở attempt mới. Trang đang tiếp tục đồng bộ; retry chỉ hiện khi backend ghi FAILED và lỗi cho phép thử lại.";
  } else if (progress.status === "FAILED") {
    title = "Xử lý chưa hoàn tất";
    description = progress.error?.retryable
      ? "Xem nguyên nhân ở giai đoạn lỗi. Sau khi xử lý được nguyên nhân, có thể tạo attempt mới."
      : progress.error
        ? "Lỗi của attempt này cần được khắc phục trước; backend chưa cho phép tạo attempt mới."
        : "Backend chưa ghi lỗi retryable cho attempt này. Tải lại trạng thái hoặc tạo job mới sau khi xử lý nguyên nhân.";
  } else if (progress.status === "CANCELLED") {
    title = "Đã huỷ xử lý";
    description = "Kết quả đã publish vẫn được giữ; mở giai đoạn hoàn tất để xem.";
  } else if (progress.waiting_for === "resources") {
    title = "Đang chờ tài nguyên";
    description = "Giữ nguyên cấu hình đã chọn. Máy xử lý kiểm tra lại và tự chạy tiếp khi đủ tài nguyên; có thể rời trang hoặc huỷ job.";
  } else if (progress.waiting_for === "anonymization_review") {
    title = "Cần bạn xem bản đã che";
    description = "Khuôn mặt và biển số phát hiện được đã bị che. Xem lại rồi xác nhận để pipeline dựng 3D, hoặc huỷ job.";
    action = { label: "Xem bản đã che", tab: "progress" };
  } else if (progress.waiting_for === "metric_confirmation") {
    // Hiện trong chuông; nút tương ứng cũng nằm ngay ở bước đang chờ trong timeline Tiến trình.
    title = "Cần bạn xác nhận tỉ lệ mét";
    description = "Chọn điểm và nhập kích thước thật để pipeline tiếp tục.";
    action = { label: "Xác nhận tỉ lệ mét", tab: "studio", mode: "metric" };
  } else if (progress.status === "QUEUED") {
    title = "Đang chờ worker";
    description = "Job đã vào hàng đợi. Theo dõi các giai đoạn bên dưới.";
  } else if (sceneReady) {
    title = "Đang đọc bước tiếp theo";
    description = "Đối chiếu vật thể, gói và trạng thái duyệt của revision hiện tại.";
    reading = true;
    if (detail && (revision === null || detail.scene.scene_revision === revision)) {
      reading = false;
      // Ứng viên do pipeline tạo có `active=false` cho tới khi được xác nhận, nên đếm theo trạng thái (cùng quy tắc
      // với bộ lọc "Chờ xác nhận" của Studio), không theo cờ `active`.
      const review_of = (object: SceneIR["objects"][number]) => object.provenance.review;
      const pending = detail.scene.objects.filter((object) => object.state === "CANDIDATE" && review_of(object) !== "IGNORED" && review_of(object) !== "DELETED").length;
      pendingCount = pending;
      const awaitingChoice = detail.scene.provenance.object_extraction === "objectify_failed_awaiting_choice";
      const pkg = detail.pkg?.scene_revision === detail.scene.scene_revision ? detail.pkg : null;
      const review = detail.review?.record.scene_revision === detail.scene.scene_revision ? detail.review : null;
      // Draft: chưa có collider theo vật nên không đóng gói được. Nhánh này đứng trước các nhánh "sẵn sàng tạo gói".
      const draft = objectGeometryState(detail.scene) === "awaiting_review";
      if (draft && geometry?.state === "failed") {
        title = "Tạo mesh chưa xong";
        description = geometry.error ?? "Chỉnh vùng rồi thử lại Tạo mesh.";
        action = { label: "Mở để sửa vùng", tab: "studio", mode: "scene" };
      } else if (draft) {
        title = "Duyệt vật rồi Tạo mesh";
        description = pending > 0
          ? `${pending} vật chờ xác nhận. Chỉnh vùng nếu cần, rồi bấm Tạo mesh trong Studio.`
          : "Chỉnh vùng nếu cần, rồi bấm Tạo mesh trong Studio.";
        action = { label: "Mở để duyệt", tab: "studio", mode: "scene" };
      } else if (awaitingChoice) {
        // Pipeline v2: tách theo vật lỗi hết số lần thử; scene chỉ có môi trường cho tới khi người dùng chọn.
        title = "Tách theo vật chưa thành công";
        description = "Chạy lại tách theo vật hoặc dùng hộp ứng viên ngay tại bước “Tách vật thể”.";
        action = { label: "Xem bước tách vật thể", tab: "progress" };
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
  if (action?.tab === "studio" && !canMutateJob) action = null;
  const atTarget = action && current === action.tab && (!action.mode || mode === action.mode);
  const showRetry = Boolean(!retryState && canRetryJob && progress.status === "FAILED" && progress.error?.retryable);
  const empty = !title && !showRetry && !(sceneReady && error);
  // Chuông là nơi duy nhất hiện thông báo của trang job nên luôn có mặt; không có gì thì nói rõ là không có.
  if (empty && variant !== "popover") return null;

  if (variant === "popover") {
    const hasAlert = Boolean((title && !reading) || showRetry || (sceneReady && error));
    return (
      <div className="relative" ref={popoverRef}>
        <button
          type="button"
          aria-label="Thông báo của scene"
          aria-expanded={isOpen}
          onClick={() => setIsOpen((prev) => !prev)}
          className={cn(
            "relative flex h-8 w-8 items-center justify-center rounded-md border border-line bg-paper text-ink transition hover:bg-paper-raised hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ember-strong",
            isOpen && "border-line-strong bg-paper-raised"
          )}
        >
          <Bell className="h-4 w-4" aria-hidden />
          {pendingCount !== null && pendingCount > 0 ? (
            <span className="absolute -top-1.5 -right-1.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-ember-strong px-1 text-[10px] font-bold leading-none text-on-accent shadow-sm">
              {pendingCount > 99 ? "99+" : pendingCount}
            </span>
          ) : hasAlert ? (
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-ember-strong ring-2 ring-paper" />
          ) : null}
        </button>

        {isOpen && (
          <div
            role="dialog"
            aria-label="Thông báo của scene"
            className="absolute right-0 top-full z-50 mt-2 w-80 rounded-lg border border-line-strong bg-paper p-4 shadow-xl sm:w-96"
          >
            <div className="mb-3 flex items-center justify-between border-b border-line pb-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                <Bell className="h-3.5 w-3.5" aria-hidden />
                <span>Thông báo</span>
              </div>
              <button
                type="button"
                aria-label="Đóng"
                onClick={() => setIsOpen(false)}
                className="rounded p-1 text-ink-muted hover:bg-paper-raised hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ember-strong"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>

            {empty && <p className="text-sm text-ink-muted">Không có thông báo nào.</p>}
            {title && (
              <div className="space-y-1">
                <p className="text-sm font-bold text-ink">{title}</p>
                {description && <p className="text-xs leading-relaxed text-ink-muted">{description}</p>}
              </div>
            )}

            {(showRetry || (action && !atTarget)) && (
              <div className="mt-3.5 flex items-center justify-end gap-2 border-t border-line/60 pt-2">
                {showRetry && (
                  <div className="space-y-2 text-right">
                    {isGuest && (
                      <>
                        <p className="text-xs text-ink-muted">Retry thủ công dùng 1 lượt Guest khi máy chủ chấp nhận.</p>
                        <GuestQuotaStatus quota={guestQuota} />
                      </>
                    )}
                    <Button size="sm" disabled={busy || guestQuotaExhausted} onClick={onRetry}>
                      Thử lại
                    </Button>
                  </div>
                )}
                {action && !atTarget && (
                  <Button size="sm" onClick={() => { setIsOpen(false); onOpen(action!.tab, action!.mode); }}>
                    {action.label}
                  </Button>
                )}
              </div>
            )}

            {sceneReady && error && (
              <ErrorFeedback
                message={error}
                className="mt-3"
                retryLabel="Tải lại dữ liệu"
                retry={() => void load(new AbortController().signal)}
              />
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <section aria-label="Bước tiếp theo" className="border-b border-line bg-paper px-4 py-3 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {title && <div className="min-w-0"><p className="text-sm font-bold">{title}</p>{description && <p className="mt-0.5 text-sm text-ink-muted">{description}</p>}</div>}
        {showRetry && (
          <div className="space-y-2 text-right">
            {isGuest && (
              <>
                <p className="text-xs text-ink-muted">Retry thủ công dùng 1 lượt Guest khi máy chủ chấp nhận.</p>
                <GuestQuotaStatus quota={guestQuota} />
              </>
            )}
            <Button size="sm" disabled={busy || guestQuotaExhausted} onClick={onRetry}>Thử lại</Button>
          </div>
        )}
        {action && !atTarget && <Button size="sm" onClick={() => onOpen(action!.tab, action!.mode)}>{action.label}</Button>}
      </div>
      {sceneReady && error && <ErrorFeedback message={error} className="mt-2" retryLabel="Tải lại dữ liệu" retry={() => void load(new AbortController().signal)} />}
    </section>
  );
}
