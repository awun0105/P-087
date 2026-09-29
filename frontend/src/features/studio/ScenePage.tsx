"use client";

import { Clock, Loader2, RotateCcw, Server, Square } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, Notice, formatBytes } from "@/components/studio/primitives";
import { FlowStepper } from "@/features/studio/FlowStepper";
import { PipelineTimeline, type StageView } from "@/features/studio/PipelineTimeline";
import { STUDIO_STAGES } from "@/features/studio/stages";
import { SceneWorkspace } from "@/features/studio/SceneWorkspace";
import { usePolling } from "@/features/studio/usePolling";
import { getJob, getPreview, getProject, jobArtifactContentUrl } from "@/lib/api/endpoints";
import { cancelJob, getJobProgress, retryJob } from "@/lib/api/studio";
import type { JobProgress } from "@/lib/contracts/studio";

const STEPS = [
  { key: "upload", label: "Tải video lên" },
  { key: "select", label: "Chọn video" },
  { key: "process", label: "Xử lý" },
  { key: "scene", label: "Mở scene" },
] as const;

interface SceneInfo {
  name: string;
  videoName: string | null;
  videoSize: number | null;
}

/** Theo dõi job theo stage (dữ liệu thật từ backend); preview sẵn sàng → editor 3D. */
export function ScenePage({ jobId }: { jobId: string }) {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [info, setInfo] = useState<SceneInfo | null>(null);
  const [preview, setPreview] = useState<{ url: string; filename: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const now = useNow(progress?.status === "RUNNING" || progress?.status === "QUEUED");

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

  const settled = preview !== null || progress?.status === "FAILED" || progress?.status === "CANCELLED";
  usePolling(poll, 3000, !settled);

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

  if (preview) {
    return (
      <SceneWorkspace
        title={info?.name ?? "Scene"}
        backHref="/"
        contentUrl={preview.url}
        filename={preview.filename}
        badges={<Badge tone="sage">Dựng từ video của bạn</Badge>}
      />
    );
  }

  const views: StageView[] =
    progress?.stages.map((stage) => ({
      stage_id: stage.stage_id,
      state: stage.state,
      error: stage.error,
      fraction: null,
      seconds: stageSeconds(stage.started_at, stage.completed_at, stage.state === "running" ? now : null),
    })) ?? [];

  return (
    <main className="mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">{info?.name ?? "Scene"}</h1>
        {progress && progress.attempt > 1 && <Badge tone="neutral">Lần chạy {progress.attempt}</Badge>}
      </div>
      <div className="mt-8">
        <FlowStepper steps={STEPS} current={2} />
      </div>
      {error && (
        <Notice tone="rust" className="mt-6">
          {error}
        </Notice>
      )}
      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_24rem]">
        <div className="space-y-4">
          <StatusPanel progress={progress} now={now} />
          {info?.videoName && (
            <Card className="flex items-center gap-3 p-4 text-sm">
              <Server className="size-4 shrink-0 text-ink-muted" aria-hidden />
              <span className="min-w-0 truncate text-ink-muted">
                Video gốc: <span className="font-medium text-ink">{info.videoName}</span>
                {info.videoSize !== null && ` · ${formatBytes(info.videoSize)}`}
              </span>
            </Card>
          )}
        </div>
        <Card className="h-fit p-5 sm:p-6">
          {progress ? (
            <PipelineTimeline
              stages={views}
              stageList={STUDIO_STAGES}
              timeNote={`Cập nhật ${new Date(progress.updated_at).toLocaleTimeString("vi-VN")}`}
            />
          ) : (
            <p className="flex items-center gap-2 text-sm text-ink-muted" role="status">
              <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
              Đang tải tiến trình…
            </p>
          )}
          <div className="mt-6 flex justify-end gap-2">
            {(progress?.status === "RUNNING" || progress?.status === "QUEUED") && (
              <Button
                variant="danger"
                size="sm"
                disabled={busy}
                onClick={() => {
                  if (window.confirm("Hủy xử lý scene này? Tiến trình trên GPU sẽ dừng.")) void act(() => cancelJob(jobId));
                }}
              >
                <Square aria-hidden />
                Hủy xử lý
              </Button>
            )}
            {progress?.status === "FAILED" && (
              <Button size="sm" disabled={busy} onClick={() => void act(() => retryJob(jobId))}>
                <RotateCcw aria-hidden />
                Thử lại
              </Button>
            )}
          </div>
        </Card>
      </div>
    </main>
  );
}

function StatusPanel({ progress, now }: { progress: JobProgress | null; now: number }) {
  if (!progress) return <Card className="h-40 animate-pulse motion-reduce:animate-none" />;
  if (progress.status === "QUEUED") {
    return (
      <Notice tone="ochre" icon={<Clock aria-hidden />}>
        <p className="font-medium text-ink">Đang chờ worker GPU nhận job</p>
        <p className="mt-1">
          Job đã vào hàng đợi. Nếu chờ lâu, kiểm tra worker đang chạy:{" "}
          <code className="rounded bg-paper-sunken px-1 font-mono text-xs">python -m src.services.orchestration.jobs.worker_cli</code>
        </p>
      </Notice>
    );
  }
  if (progress.status === "FAILED") {
    return (
      <Notice tone="rust">
        <p className="font-medium">Xử lý thất bại</p>
        <p className="mt-1">{progress.error?.human_message ?? "Worker dừng trước khi hoàn tất."} Video gốc vẫn được giữ; bấm Thử lại để chạy lần mới.</p>
      </Notice>
    );
  }
  if (progress.status === "CANCELLED") {
    return <Notice>Đã hủy xử lý scene này.</Notice>;
  }
  const elapsed = Math.max(0, (now - Date.parse(progress.started_at)) / 1000);
  return (
    <Card className="p-5 sm:p-6">
      <p className="text-sm font-medium text-ink">Đang dựng scene trên máy chủ</p>
      <p className="mt-1 text-sm leading-relaxed text-ink-muted">
        Bạn có thể đóng trang này; job vẫn chạy và sẽ hiện trong Scenes. Đã chạy {Math.floor(elapsed / 60)} phút{" "}
        {Math.floor(elapsed % 60)} giây.
      </p>
    </Card>
  );
}

function stageSeconds(started: string | null, completed: string | null, now: number | null): number | null {
  if (!started) return null;
  const end = completed ? Date.parse(completed) : now;
  if (end === null) return null;
  return Math.max(0, (end - Date.parse(started)) / 1000);
}

/** Đồng hồ 1 giây cho thời gian đã chạy; tắt khi job không còn chạy. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}
