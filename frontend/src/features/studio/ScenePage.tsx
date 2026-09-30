"use client";

import { Box, Package, Pencil, RotateCcw, Ruler, ShieldCheck, Workflow } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import type { SaveState } from "@/features/studio/ObjectReviewView";
import { GeometryBadge, MetricBadge, ModeButton, SaveStatus } from "@/features/studio/scene/badges";
import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import { ResultsTab } from "@/features/studio/scene/ResultsTab";
import { ReviewTab } from "@/features/studio/scene/ReviewTab";
import { metricState, stageState, type Preview, type SceneInfo, type StudioMode, type Tab } from "@/features/studio/scene/state";
import { StudioTab } from "@/features/studio/scene/StudioTab";
import { usePolling } from "@/features/studio/usePolling";
import { getJob, getPreview, getProject, jobArtifactContentUrl } from "@/lib/api/endpoints";
import { cancelJob, getJobProgress, retryJob } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { JobProgress } from "@/lib/contracts/studio";

/**
 * Ngữ cảnh một scene dựng từ video (PRODUCT.md §3.1, D-07): header giữ tên scene, trạng thái và
 * một CTA theo trạng thái; bốn tab Tiến trình · Studio · Kiểm tra & duyệt · Kết quả. Trạng thái bền
 * vững ở backend; màn này chỉ giữ tab/chế độ đang xem.
 */
export function ScenePage({ jobId }: { jobId: string }) {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [info, setInfo] = useState<SceneInfo | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab | null>(null);
  const [mode, setMode] = useState<StudioMode>("scene");
  const [save, setSave] = useState<SaveState | null>(null);

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
  const current: Tab = tab ?? (preview ? "studio" : "progress");
  const studioMode: StudioMode = waitingMetric && preview ? (mode === "gaussian" ? "gaussian" : "metric") : mode === "metric" ? "scene" : mode;

  const tabs: { id: Tab; label: string; icon: ReactNode; locked: string | null }[] = [
    { id: "progress", label: "Tiến trình", icon: <Workflow aria-hidden />, locked: null },
    { id: "studio", label: "Studio", icon: <Box aria-hidden />, locked: preview ? null : "Có khi bản xem 3DGS dựng xong" },
    { id: "review", label: "Kiểm tra & duyệt", icon: <ShieldCheck aria-hidden />, locked: sceneReady ? null : "Có sau khi dựng collision và tách vật thể" },
    { id: "results", label: "Kết quả", icon: <Package aria-hidden />, locked: preview ? null : "Có khi bản xem 3DGS dựng xong" },
  ];

  return (
    <main className="flex h-[calc(100dvh-3rem)] flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-paper-raised px-4 py-2.5 sm:px-6">
        <h1 className="mr-1 truncate text-base font-semibold">{info?.name ?? "Scene"}</h1>
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
        </div>
      </div>
      <nav className="flex items-center gap-1 overflow-x-auto border-b border-line bg-paper px-4 py-1.5 sm:px-6" role="tablist" aria-label="Vùng của scene">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={current === item.id}
            disabled={item.locked !== null}
            title={item.locked ?? undefined}
            onClick={() => setTab(item.id)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40 [&_svg]:size-4",
              current === item.id ? "bg-ember-soft font-medium text-ember-strong" : "text-ink-muted hover:bg-paper-sunken hover:text-ink",
            )}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
        {current === "studio" && preview && (
          <div className="ml-auto flex shrink-0 items-center gap-1" role="group" aria-label="Chế độ Studio">
            {!waitingMetric && (
              <ModeButton active={studioMode === "scene"} onClick={() => setMode("scene")}>
                Scene
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
        )}
      </nav>
      {error && (
        <Notice tone="rust" className="m-3">
          {error}
        </Notice>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
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
        {current === "studio" && preview && (
          <StudioTab
            jobId={jobId}
            title={info?.name ?? "Scene"}
            preview={preview}
            mode={studioMode}
            geometry={geometry}
            sceneReady={sceneReady}
            onSaveState={setSave}
            onMetricClose={() => setMode("scene")}
            onMetricConfirmed={() => {
              setMode("scene");
              void poll(new AbortController().signal);
            }}
          />
        )}
        {current === "review" && <ReviewTab jobId={jobId} onSaveState={setSave} />}
        {current === "results" && preview && <ResultsTab jobId={jobId} preview={preview} />}
      </div>
    </main>
  );
}
