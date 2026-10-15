"use client";

import { ApiError } from "@/lib/api/client";
import { isGuestQuotaExceededError, resourceCapabilityAllowed } from "@/lib/api/auth";
import { errorMessage } from "@/lib/ui-error";

import dynamic from "next/dynamic";
import { ArrowLeft, Box, Package, Pencil, ShieldCheck, Workflow } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/studio/primitives";
import { usePageTitle } from "@/features/shell/Breadcrumbs";
import type { SaveState } from "@/features/studio/ObjectReviewView";
import { GeometryBadge, MetricBadge, ModeButton, SaveStatus } from "@/features/studio/scene/badges";
import { DemoControls } from "@/features/studio/scene/DemoControls";
import { SceneTabs, type SceneTabItem } from "@/features/studio/scene/SceneTabs";
import { GAUSSIAN_EDIT_ENABLED, metricState, stageState, type Preview, type SceneInfo, type StudioMode, type Tab } from "@/features/studio/scene/state";
import { ObjectifyContext } from "@/features/studio/scene/objectifyContext";
import { geometryReviewStep, useObjectifyState } from "@/features/studio/scene/useObjectify";
import { progressSceneStatus } from "@/features/studio/sceneStatus";
import { usePolling } from "@/features/studio/usePolling";
import { getJob, getPreview, getProject, jobArtifactContentUrl } from "@/lib/api/endpoints";
import { cancelJob, getJobProgress, retryJob } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import { useUrlState } from "@/features/studio/useUrlState";
import { useNavigationGuard } from "@/features/shell/NavigationGuard";
import { useAuth } from "@/features/studio/AuthProvider";
import { NextAction } from "@/features/studio/scene/NextAction";
import { ErrorFeedback, notifySuccess } from "@/components/studio/feedback";
import type { MetricDraft } from "@/features/studio/MetricConfirmView";
import type { JobProgress } from "@/lib/contracts/studio";

interface RetrySync {
  jobId: string;
  fromAttempt: number;
  afterPollId: number;
  status: "submitting" | "accepted" | "rejected" | "uncertain";
  message?: string;
}

const PROGRESS_STATUS_ORDER = { QUEUED: 0, RUNNING: 1, SUCCEEDED: 2, FAILED: 2, CANCELLED: 2 } as const;

/**
 * Mỗi tab là một chunk riêng: three.js (kết quả từng bước) và PlayCanvas (Studio) chỉ tải khi mở
 * tab cần chúng, trang scene không phải tải trước toàn bộ viewer.
 */
function TabLoading() {
  return (
    <p className="flex items-center gap-2 p-6 text-sm text-ink-muted" role="status">
      Đang tải…
    </p>
  );
}
const ProgressTab = dynamic(() => import("@/features/studio/scene/ProgressTab").then((m) => m.ProgressTab), { loading: TabLoading, ssr: false });
const StudioTab = dynamic(() => import("@/features/studio/scene/StudioTab").then((m) => m.StudioTab), { loading: TabLoading, ssr: false });
const ReviewTab = dynamic(() => import("@/features/studio/scene/ReviewTab").then((m) => m.ReviewTab), { loading: TabLoading, ssr: false });
const ResultsTab = dynamic(() => import("@/features/studio/scene/ResultsTab").then((m) => m.ResultsTab), { loading: TabLoading, ssr: false });

/**
 * Ngữ cảnh một scene dựng từ video (STUDIO_UX_SPEC.md §3.1, D-07): header giữ tên scene, trạng thái và
 * một CTA theo trạng thái; bốn tab Tiến trình · Studio · Kiểm tra & duyệt · Kết quả. Trạng thái bền
 * vững ở backend; màn này chỉ giữ tab/chế độ đang xem.
 */
export function ScenePage({ jobId, initialTab }: { jobId: string; initialTab?: "progress" }) {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [info, setInfo] = useState<SceneInfo | null>(null);
  const [loadedPreview, setPreview] = useState<(Preview & { attempt: number }) | null>(null);
  const preview = loadedPreview?.attempt === progress?.attempt ? loadedPreview : null;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pollingKey, setPollingKey] = useState(0);
  const [retrySync, setRetrySync] = useState<RetrySync | null>(null);
  const retryInFlight = useRef(false);
  const pollSequence = useRef(0);
  const latestAppliedPoll = useRef<{ jobId: string; pollId: number; progress: JobProgress } | null>(null);
  const retrySyncRef = useRef<RetrySync | null>(null);
  const [tab, setTab] = useState<Tab | null>(initialTab ?? null);
  const { params, update } = useUrlState();
  const { navigate } = useNavigationGuard();
  const { me, refresh } = useAuth();
  const isGuest = me?.user?.role === "guest";
  const guestQuotaExhausted = isGuest && me?.quota?.remaining === 0;
  const canMutateJob = resourceCapabilityAllowed(me, progress?.capabilities?.can_mutate);
  const canRetryJob = resourceCapabilityAllowed(me, progress?.capabilities?.can_retry);
  const canCancelJob = resourceCapabilityAllowed(me, progress?.capabilities?.can_cancel)
    && (progress?.status === "RUNNING" || progress?.status === "QUEUED")
    && progress.waiting_for !== "metric_confirmation";
  const requestedMode = params.get("mode");
  const mode: StudioMode = requestedMode === "metric" || (requestedMode === "gaussian" && GAUSSIAN_EDIT_ENABLED) ? requestedMode : "scene";
  const [save, setSave] = useState<SaveState | null>(null);
  const metricScope = jobId + ":" + progress?.attempt + ":" + preview?.url;
  const [measurement, setMeasurement] = useState<{ scope: string; draft: MetricDraft } | null>(null);
  const metricDraft = measurement?.scope === metricScope ? measurement.draft : undefined;
  const rememberMetric = useCallback((draft: MetricDraft) => setMeasurement({ scope: metricScope, draft }), [metricScope]);
  // Studio giữ sống sau lần mở đầu: đổi tab rồi quay lại không phải tải lại 3DGS lên GPU.
  const [studioVisited, setStudioVisited] = useState(false);
  usePageTitle(info?.name ?? null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const job = await getJob(jobId);
      if (!job.ok || !alive) return;
      const project = await getProject(job.data.project_id);
      if (!project.ok || !alive) return;
      const video = project.data.input_video;
      setInfo({ name: project.data.name, videoName: video?.original_name ?? null, videoSize: video?.size_bytes ?? null, createdBy: project.data.created_by?.display_name ?? null });
    })();
    return () => {
      alive = false;
    };
  }, [jobId]);

  const poll = useCallback(
    async (signal: AbortSignal) => {
      const pollId = ++pollSequence.current;
      const result = await getJobProgress(jobId, signal);
      if (signal.aborted) return;
      const latest = latestAppliedPoll.current;
      if (latest?.jobId === jobId && pollId < latest.pollId) return;
      if (!result.ok) {
        if (result.error.status === 404) {
          if (latest?.jobId === jobId) latestAppliedPoll.current = { ...latest, pollId };
          retrySyncRef.current = null;
          setRetrySync(null);
          setProgress(null);
          setError("Không tìm thấy scene này.");
        } else {
          setError(errorMessage(result.error));
        }
        return;
      }
      if (latest?.jobId === jobId) {
        const olderAttempt = result.data.attempt < latest.progress.attempt;
        const terminalChanged = PROGRESS_STATUS_ORDER[latest.progress.status] === 2
          && result.data.status !== latest.progress.status;
        const sameAttemptRegressed = result.data.attempt === latest.progress.attempt && (
          Date.parse(result.data.updated_at) < Date.parse(latest.progress.updated_at)
          || PROGRESS_STATUS_ORDER[result.data.status] < PROGRESS_STATUS_ORDER[latest.progress.status]
          || terminalChanged
        );
        if (olderAttempt || sameAttemptRegressed) return;
      }
      latestAppliedPoll.current = { jobId, pollId, progress: result.data };
      const pendingRetry = retrySyncRef.current;
      let retryNotice: string | null = null;
      let acknowledgedAttempt: number | null = null;
      if (
        pendingRetry?.jobId === jobId
        && pendingRetry.status !== "submitting"
        && pollId >= pendingRetry.afterPollId
      ) {
        if (result.data.attempt > pendingRetry.fromAttempt) {
          retrySyncRef.current = null;
          setRetrySync(null);
          acknowledgedAttempt = result.data.attempt;
        } else if (result.data.status === "FAILED" && pendingRetry.status !== "accepted") {
          retrySyncRef.current = null;
          setRetrySync(null);
          retryNotice = pendingRetry.status === "rejected"
            ? pendingRetry.message ?? "Máy chủ từ chối yêu cầu thử lại; attempt FAILED hiện tại vẫn được giữ."
            : "Chưa nhận được xác nhận từ yêu cầu thử lại; trạng thái mới nhất vẫn là FAILED nên bạn có thể thử lại.";
        } else if (result.data.status === "SUCCEEDED" || result.data.status === "CANCELLED") {
          retrySyncRef.current = null;
          setRetrySync(null);
        }
      }
      setError(null);
      setProgress(result.data);
      if (acknowledgedAttempt !== null) notifySuccess(`Máy chủ đã ghi nhận lần chạy ${acknowledgedAttempt}.`);
      if (retryNotice !== null) setError(retryNotice);
      // Mặc định luôn là Tiến trình (trạng thái, lỗi, bước tiếp theo); chỉ áp trên lần đọc đầu, không giật tab người đang xem.
      setTab((selected) => selected ?? "progress");
      if (result.data.preview_ready && loadedPreview?.attempt !== result.data.attempt) {
        const loaded = await getPreview(jobId);
        if (loaded.ok) {
          setPreview({
            attempt: result.data.attempt,
            url: jobArtifactContentUrl(jobId, loaded.data.delivery_ref),
            filename: loaded.data.delivery_ref.artifact_uri.split("/").pop() ?? "scene.sog",
          });
        } else {
          setError(`Preview đã publish nhưng không đọc được: ${errorMessage(loaded.error)}`);
        }
      }
    },
    [jobId, loadedPreview],
  );

  const finished = progress?.status === "SUCCEEDED" || progress?.status === "FAILED" || progress?.status === "CANCELLED";
  const waitingMetric = progress?.waiting_for === "metric_confirmation";
  const retryPending = retrySync?.jobId === jobId;
  // Dừng poll khi job kết thúc hoặc đang chờ chính người dùng; tiếp tục khi worker còn làm.
  usePolling(async (signal) => { await poll(signal); }, 3000, retryPending || !(finished || (preview !== null && waitingMetric)), pollingKey);

  async function act(action: () => Promise<unknown>, success: string) {
    if (busy) return;
    setBusy(true);
    try {
      await action();
      notifySuccess(success);
      setPollingKey((k) => k + 1);
    } catch (cause) {
      setError(errorMessage(cause, "Thao tác thất bại"));
    } finally {
      setBusy(false);
    }
  }

  async function requestRetry() {
    if (!canRetryJob || busy || retryInFlight.current || retryPending) return;
    const failed = progress;
    if (!failed || failed.job_id !== jobId || failed.status !== "FAILED" || !failed.error?.retryable) {
      await poll(new AbortController().signal);
      return;
    }

    retryInFlight.current = true;
    setBusy(true);
    setError(null);
    const submitting: RetrySync = { jobId, fromAttempt: failed.attempt, afterPollId: pollSequence.current + 1, status: "submitting" };
    retrySyncRef.current = submitting;
    setRetrySync(submitting);
    let retryStatus: "accepted" | "rejected" | "uncertain" = "accepted";
    let message: string | undefined;
    try {
      await retryJob(jobId);
      if (isGuest) void refresh();
    } catch (cause) {
      retryStatus = cause instanceof ApiError && cause.isClientError ? "rejected" : "uncertain";
      if (isGuest && isGuestQuotaExceededError(cause)) {
        await refresh();
        message = "Máy chủ báo đã hết lượt Guest ở thời điểm gửi. Hạn mức hiện tại đã được tải lại.";
      } else {
        message = errorMessage(cause, "Chưa xác nhận được yêu cầu thử lại.");
      }
    }

    const afterPollId = pollSequence.current + 1;
    const retrying: RetrySync = { jobId, fromAttempt: failed.attempt, afterPollId, status: retryStatus, message };
    retrySyncRef.current = retrying;
    setRetrySync(retrying);
    try {
      await poll(new AbortController().signal);
    } finally {
      retryInFlight.current = false;
      setBusy(false);
    }
  }

  function startRetry() {
    void navigate(() => { void requestRetry(); }, undefined, true);
  }

  const metric = metricState(progress);
  const geometry = stageState(progress, "ST-RGB-GEOMETRY");
  const sceneReady = stageState(progress, "ST-OBJECT-EXTRACT") === "succeeded" || (progress?.status === "SUCCEEDED" && geometry === "succeeded");
  // Tab mặc định theo tình huống; người dùng đổi tab thì giữ lựa chọn đó (stage mới không cưỡng ép đổi màn).
  const requestedTab = params.get("tab");
  const selected: Tab = requestedTab === "progress" || requestedTab === "studio" || requestedTab === "review" || requestedTab === "results" ? requestedTab : tab ?? "progress";
  // Một trạng thái tách vật thể cho cả trang: hàng bước ở Tiến trình, thông báo trong Studio, chuông và huy hiệu đầu trang.
  const objectify = useObjectifyState({
    jobId,
    enabled: sceneReady,
    onRevision: (revision) => { setSave({ status: "saved", revision }); setPollingKey((k) => k + 1); },
  });
  const status = progress
    ? progressSceneStatus(progress, objectify.state?.awaiting_choice === true && !objectify.pending, geometryReviewStep(objectify.state))
    : null;
  const studioMode: StudioMode = mode === "metric" && !waitingMetric ? "scene" : mode;

  const tabs: SceneTabItem[] = [
    { id: "progress", label: "Tiến trình", icon: <Workflow aria-hidden />, locked: null },
    { id: "studio", label: "Studio", icon: <Box aria-hidden />, locked: preview ? null : "Có khi bản xem 3DGS dựng xong" },
    { id: "review", label: "Kiểm tra & duyệt", icon: <ShieldCheck aria-hidden />, locked: sceneReady ? null : "Có sau khi dựng collision và tách vật thể" },
    { id: "results", label: "Kết quả", icon: <Package aria-hidden />, locked: preview ? null : "Có khi bản xem 3DGS dựng xong" },
  ];

  const locked = tabs.find((item) => item.id === selected)?.locked;
  const current: Tab = locked ? "progress" : selected;
  function openTab(next: Tab, nextMode?: StudioMode) {
    const target = new URL(window.location.href);
    target.searchParams.set("tab", next);
    if (nextMode) target.searchParams.set("mode", nextMode);
    void navigate(() => { update({ tab: next, ...(nextMode ? { mode: nextMode } : {}) }); }, target.href);
  }
  function setMode(next: StudioMode) { openTab("studio", next); }
  useEffect(() => {
    if (current !== "studio") return;
    const timer = setTimeout(() => setStudioVisited(true), 0);
    return () => clearTimeout(timer);
  }, [current]);

  return (
    <ObjectifyContext.Provider value={objectify}>
    <main aria-label={current === "studio" ? "Studio toàn màn hình" : undefined} className={cn("flex flex-col", current === "studio" ? "fixed inset-0 z-40 h-dvh bg-paper" : "h-[calc(100dvh-3rem)]")}>
      <div className="relative z-20 flex flex-wrap items-center gap-2 border-b border-line bg-paper-raised px-4 py-3 sm:px-6">
        {current === "studio" && <button type="button" aria-label="Thoát Studio, về Tiến trình" title="Về Tiến trình" onClick={() => openTab("progress")}
          className="flex size-9 shrink-0 items-center justify-center rounded-lg text-ink-muted hover:bg-paper-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember">
          <ArrowLeft className="size-5" aria-hidden />
        </button>}
        <div className="mr-2 min-w-0">
          <h1 className="truncate text-base font-bold">{info?.name ?? "Đang tải scene…"}</h1>
        </div>
        {status && <Badge tone={status.tone}>{status.label}</Badge>}
        {progress && progress.attempt > 1 && <Badge tone="neutral">Lần chạy {progress.attempt}</Badge>}
        {preview && <MetricBadge state={metric} />}
        <GeometryBadge state={geometry} />
        {save && <SaveStatus state={save} />}
        <div className="ml-auto flex items-center gap-2">
          {/* Chuông thông báo dùng chung cho mọi tab của trang job; không còn khung thông báo riêng dưới thanh tab. */}
          <NextAction
            jobId={jobId}
            progress={progress}
            current={current}
            mode={studioMode}
            sceneReady={sceneReady}
            revision={save?.revision ?? null}
            busy={busy}
            onOpen={openTab}
            onRetry={startRetry}
            retryState={retryPending ? retrySync?.status ?? null : null}
            canMutateJob={canMutateJob}
            canRetryJob={canRetryJob}
            variant="popover"
          />
          {canMutateJob && <DemoControls scope="publication" jobId={jobId} revision={save?.revision ?? null} sceneReady={sceneReady} defaultTitle={info?.name ?? ""}
            onRestored={(revision) => setSave({ status: "saved", revision })} />}
        </div>
      </div>
      {current !== "studio" && <SceneTabs tabs={tabs} current={current} onChange={(next) => openTab(next)} />}
      {locked && <p role="status" className="px-4 py-2 text-sm text-ink-muted">{locked}. Đang hiển thị Tiến trình.</p>}
      {requestedTab && !["progress", "studio", "review", "results"].includes(requestedTab) && <p role="status" className="px-4 py-2 text-sm text-ink-muted">Tab không hợp lệ; đã mở vùng mặc định.</p>}
      {current === "studio" && preview && (waitingMetric || GAUSSIAN_EDIT_ENABLED) && (
        <div className="flex items-center justify-end gap-2 border-b border-line bg-paper-raised px-4 py-1.5 sm:px-6">
          {canMutateJob ? (
            <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Chế độ Studio">
              <ModeButton active={studioMode === "scene"} onClick={() => setMode("scene")}>
                {sceneReady ? "Vật thể" : "Scene 3D"}
              </ModeButton>
              {waitingMetric && (
                <ModeButton active={studioMode === "metric"} onClick={() => setMode("metric")}>
                  Tỉ lệ mét
                </ModeButton>
              )}
              {GAUSSIAN_EDIT_ENABLED && (
                <ModeButton active={studioMode === "gaussian"} onClick={() => setMode("gaussian")}>
                  <Pencil aria-hidden /> Chỉnh Gaussian
                </ModeButton>
              )}
            </div>
          ) : <p className="text-xs text-ink-muted">Quyền chỉ xem</p>}
        </div>
      )}
      {error && <ErrorFeedback message={error} className="m-3" retryLabel="Tải lại trạng thái" retry={() => void poll(new AbortController().signal)} />}
      <div id={`scene-panel-${current}`} role={current === "studio" ? "region" : "tabpanel"} aria-label={current === "studio" ? "Nội dung Studio" : undefined} aria-labelledby={current === "studio" ? undefined : `scene-tab-${current}`} className="relative min-h-0 flex-1 overflow-y-auto">
        {current === "studio" && !preview && <TabLoading />}
        {current === "progress" && (
          <ProgressTab
            jobId={jobId}
            progress={progress}
            info={info}
            busy={busy}
            canCancel={canCancelJob}
            canAccept={canMutateJob}
            onConfirmMetric={canMutateJob && preview ? () => openTab("studio", "metric") : undefined}
            onOpenStudio={canMutateJob ? () => openTab("studio", "scene") : undefined}
            onRetry={canRetryJob && !retryPending ? startRetry : undefined}
            retryDisabled={busy || guestQuotaExhausted}
            retryHint={guestQuotaExhausted ? "Đã hết lượt Guest hôm nay; lượt được đặt lại lúc 00:00." : undefined}
            onChanged={() => setPollingKey((k) => k + 1)}
            onCancel={() => {
              if (window.confirm("Huỷ xử lý scene này? Tiến trình trên GPU sẽ dừng.")) void act(() => cancelJob(jobId), "Đã gửi yêu cầu huỷ. Trạng thái được cập nhật từ máy chủ.");
            }}
          />
        )}
        {(current === "studio" || studioVisited) && preview && (
          <div
            className={cn("absolute inset-0", current !== "studio" && "pointer-events-none invisible")}
            aria-hidden={current !== "studio"}
          >
          <StudioTab
            key={metricScope}
            jobId={jobId}
            title={info?.name ?? "Scene"}
            canMutate={canMutateJob}
            preview={preview}
            mode={studioMode}
            geometry={geometry}
            sceneReady={sceneReady}
            revision={save?.revision ?? null}
            onSaveState={setSave}
            metricDraft={metricDraft}
            onMetricDraft={rememberMetric}
            onMetricClose={() => openTab("progress")}
            onMetricConfirmed={() => {
              update({ tab: "progress", mode: "scene" });
              void poll(new AbortController().signal);
            }}
          />
          </div>
        )}
        {current === "review" && <ReviewTab jobId={jobId} canMutateJob={canMutateJob} onSaveState={setSave} />}
        {current === "results" && preview && <ResultsTab jobId={jobId} preview={preview} revision={save?.revision ?? null}
          onOpenGaussian={GAUSSIAN_EDIT_ENABLED && canMutateJob ? () => openTab("studio", "gaussian") : undefined}
          onOpenReview={sceneReady ? () => openTab("review") : undefined}
        />}
      </div>
    </main>
    </ObjectifyContext.Provider>
  );
}
