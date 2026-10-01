"use client";

import dynamic from "next/dynamic";
import { Box, Package, Pencil, RotateCcw, Ruler, ShieldCheck, Workflow } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import { usePageTitle } from "@/features/shell/Breadcrumbs";
import type { SaveState } from "@/features/studio/ObjectReviewView";
import { GeometryBadge, MetricBadge, ModeButton, SaveStatus } from "@/features/studio/scene/badges";
import { SceneTabs, type SceneTabItem } from "@/features/studio/scene/SceneTabs";
import { metricState, stageState, type Preview, type SceneInfo, type StudioMode, type Tab } from "@/features/studio/scene/state";
import { progressSceneStatus } from "@/features/studio/sceneStatus";
import { usePolling } from "@/features/studio/usePolling";
import { getJob, getPreview, getProject, jobArtifactContentUrl } from "@/lib/api/endpoints";
import { cancelJob, getJobProgress, retryJob } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { JobProgress } from "@/lib/contracts/studio";

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
 * Ngữ cảnh một scene dựng từ video (PRODUCT.md §3.1, D-07): header giữ tên scene, trạng thái và
 * một CTA theo trạng thái; bốn tab Tiến trình · Studio · Kiểm tra & duyệt · Kết quả. Trạng thái bền
 * vững ở backend; màn này chỉ giữ tab/chế độ đang xem.
 */
export function ScenePage({ jobId, initialTab }: { jobId: string; initialTab?: "progress" }) {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [info, setInfo] = useState<SceneInfo | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab | null>(initialTab ?? null);
  const [mode, setMode] = useState<StudioMode>("scene");
  const [save, setSave] = useState<SaveState | null>(null);
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
      setInfo({ name: project.data.name, videoName: video?.original_name ?? null, videoSize: video?.size_bytes ?? null });
    })();
    return () => {
      alive = false;
    };
  }, [jobId]);

  const poll = useCallback(
    async (signal: AbortSignal) => {
      const result = await getJobProgress(jobId, signal);
      if (!result.ok) {
        setError(result.error.status === 404 ? "Không tìm thấy scene này." : result.error.detail);
        return;
      }
      setError(null);
      setProgress(result.data);
      // Chỉ chọn mặc định trên lần đọc đầu; preview xuất hiện sau đó không đẩy người đang xem tiến trình sang Studio.
      setTab((selected) => selected ?? (result.data.preview_ready ? "studio" : "progress"));
      if (result.data.preview_ready && !preview) {
        const loaded = await getPreview(jobId);
        if (loaded.ok) {
          setPreview({
            url: jobArtifactContentUrl(jobId, loaded.data.delivery_ref),
            filename: loaded.data.delivery_ref.artifact_uri.split("/").pop() ?? "scene.sog",
          });
        } else {
          setError(`Preview đã publish nhưng không đọc được: ${loaded.error.detail}`);
        }
      }
    },
    [jobId, preview],
  );

  const finished = progress?.status === "SUCCEEDED" || progress?.status === "FAILED" || progress?.status === "CANCELLED";
  const waitingMetric = progress?.waiting_for === "metric_confirmation";
  // Dừng poll khi job kết thúc hoặc đang chờ chính người dùng; tiếp tục khi worker còn làm.
  usePolling(poll, 3000, !(finished || (preview !== null && waitingMetric)));

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await poll(new AbortController().signal);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Thao tác thất bại");
    } finally {
      setBusy(false);
    }
  }

  const metric = metricState(progress);
  const geometry = stageState(progress, "ST-RGB-GEOMETRY");
  const sceneReady = stageState(progress, "ST-OBJECT-EXTRACT") === "succeeded" || (progress?.status === "SUCCEEDED" && geometry === "succeeded");
  // Tab mặc định theo tình huống; người dùng đổi tab thì giữ lựa chọn đó (stage mới không cưỡng ép đổi màn).
  const current: Tab = tab ?? "progress";
  const status = progress ? progressSceneStatus(progress) : null;
  const studioMode: StudioMode = waitingMetric && preview ? (mode === "gaussian" ? "gaussian" : "metric") : mode === "metric" ? "scene" : mode;

  const tabs: SceneTabItem[] = [
    { id: "progress", label: "Tiến trình", icon: <Workflow aria-hidden />, locked: null },
    { id: "studio", label: "Studio", icon: <Box aria-hidden />, locked: preview ? null : "Có khi bản xem 3DGS dựng xong" },
    { id: "review", label: "Kiểm tra & duyệt", icon: <ShieldCheck aria-hidden />, locked: sceneReady ? null : "Có sau khi dựng collision và tách vật thể" },
    { id: "results", label: "Kết quả", icon: <Package aria-hidden />, locked: preview ? null : "Có khi bản xem 3DGS dựng xong" },
  ];

  return (
    <main className="flex h-[calc(100dvh-3rem)] flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-paper-raised px-4 py-3 sm:px-6">
        <div className="mr-2 min-w-0">
          <h1 className="truncate text-base font-semibold">{info?.name ?? "Đang tải scene…"}</h1>
          <p className="truncate font-mono text-[10px] text-ink-subtle">{jobId}</p>
        </div>
        {status && <Badge tone={status.tone}>{status.label}</Badge>}
        {progress && progress.attempt > 1 && <Badge tone="neutral">Lần chạy {progress.attempt}</Badge>}
        {preview && <MetricBadge state={metric} />}
        <GeometryBadge state={geometry} />
        {save && <SaveStatus state={save} />}
        <div className="ml-auto flex items-center gap-2">
          {waitingMetric && preview && !(current === "studio" && studioMode === "metric") && (
            <Button size="sm" onClick={() => { setTab("studio"); setMode("metric"); }}>
              <Ruler aria-hidden />
              Xác nhận tỉ lệ mét
            </Button>
          )}
          {progress?.status === "FAILED" && (
            <Button size="sm" disabled={busy} onClick={() => void act(() => retryJob(jobId))}>
              <RotateCcw aria-hidden />
              Thử lại
            </Button>
          )}
          {preview && !waitingMetric && current !== "studio" && progress?.status !== "FAILED" && (
            <Button size="sm" onClick={() => { setTab("studio"); setMode("scene"); }}><Box aria-hidden /> Mở Studio</Button>
          )}
        </div>
      </div>
      <SceneTabs tabs={tabs} current={current} onChange={(next) => {
        if (current === "studio") setStudioVisited(true);
        setTab(next);
      }} />
      {current === "studio" && preview && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-paper-raised px-4 py-2 sm:px-6">
          <p className="text-xs text-ink-muted">
            {studioMode === "gaussian" ? "Gaussian · chỉ xuất file trong phiên editor" : studioMode === "metric" ? "Tỉ lệ mét · đo tham chiếu để tiếp tục pipeline" : "SceneObject · mỗi thao tác lưu một revision"}
          </p>
          <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Chế độ Studio">
            {!waitingMetric && (
              <ModeButton active={studioMode === "scene"} onClick={() => setMode("scene")}>
                Vật thể
              </ModeButton>
            )}
            {waitingMetric && (
              <ModeButton active={studioMode === "metric"} onClick={() => setMode("metric")}>
                Tỉ lệ mét
              </ModeButton>
            )}
            <ModeButton active={studioMode === "gaussian"} onClick={() => setMode("gaussian")}>
              <Pencil aria-hidden /> Chỉnh Gaussian
            </ModeButton>
          </div>
        </div>
      )}
      {error && (
        <Notice tone="rust" className="m-3">
          {error}
        </Notice>
      )}
      <div id={`scene-panel-${current}`} role="tabpanel" aria-labelledby={`scene-tab-${current}`} className="relative min-h-0 flex-1 overflow-y-auto">
        {current === "studio" && !preview && <TabLoading />}
        {current === "progress" && (
          <ProgressTab
            jobId={jobId}
            progress={progress}
            info={info}
            busy={busy}
            metricConfirmed={metric === "confirmed"}
            hasPreview={preview !== null}
            onCancel={() => {
              if (window.confirm("Huỷ xử lý scene này? Tiến trình trên GPU sẽ dừng.")) void act(() => cancelJob(jobId));
            }}
            onRetry={() => void act(() => retryJob(jobId))}
          />
        )}
        {(current === "studio" || studioVisited) && preview && (
          <div
            className={cn("absolute inset-0", current !== "studio" && "pointer-events-none invisible")}
            aria-hidden={current !== "studio"}
          >
          <StudioTab
            jobId={jobId}
            title={info?.name ?? "Scene"}
            preview={preview}
            mode={studioMode}
            geometry={geometry}
            sceneReady={sceneReady}
            revision={save?.revision ?? null}
            onSaveState={setSave}
            onMetricClose={() => setMode("scene")}
            onMetricConfirmed={() => {
              setMode("scene");
              void poll(new AbortController().signal);
            }}
          />
          </div>
        )}
        {current === "review" && <ReviewTab jobId={jobId} onSaveState={setSave} />}
        {current === "results" && preview && <ResultsTab jobId={jobId} preview={preview} revision={save?.revision ?? null}
          onOpenGaussian={() => { setTab("studio"); setMode("gaussian"); }}
          onOpenReview={sceneReady ? () => setTab("review") : undefined}
        />}
      </div>
    </main>
  );
}
