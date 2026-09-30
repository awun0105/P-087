"use client";

import {
  Box,
  Check,
  ClipboardCheck,
  Clock,
  Download,
  Info,
  Loader2,
  Package,
  Pencil,
  RotateCcw,
  Ruler,
  ShieldCheck,
  Square,
  TriangleAlert,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Badge, Button, Card, Notice, buttonVariants, formatBytes } from "@/components/studio/primitives";
import { EditorFrame } from "@/features/studio/EditorFrame";
import { MetricConfirmView } from "@/features/studio/MetricConfirmView";
import { ModeComparisonView } from "@/features/studio/ModeComparisonView";
import { ObjectReviewView, type SaveState } from "@/features/studio/ObjectReviewView";
import { PipelineTimeline, type StageView } from "@/features/studio/PipelineTimeline";
import { ReviewPanel } from "@/features/studio/ReviewPanel";
import { SimulationPackagePanel } from "@/features/studio/SimulationPackagePanel";
import { StageViewer } from "@/features/studio/StageViewer";
import { STUDIO_STAGES } from "@/features/studio/stages";
import { usePolling } from "@/features/studio/usePolling";
import { getJob, getPreview, getProject, jobArtifactContentUrl } from "@/lib/api/endpoints";
import {
  cancelJob,
  getJobProgress,
  getJobScene,
  getReviewState,
  getSimulationPackage,
  releaseDownloadUrl,
  retryJob,
  simulationPackageDownloadUrl,
  type ReviewStateView,
  type SimulationPackageView,
} from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { JobProgress } from "@/lib/contracts/studio";

type Tab = "progress" | "studio" | "review" | "results";
type StudioMode = "scene" | "metric" | "gaussian";

interface SceneInfo {
  name: string;
  videoName: string | null;
  videoSize: number | null;
}

interface Preview {
  url: string;
  filename: string;
}

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

function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs transition-colors [&_svg]:size-3.5",
        active ? "border-ember bg-ember-soft text-ember-strong" : "border-line text-ink-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

// ── Tiến trình ──────────────────────────────────────────────────────────────

function ProgressTab({
  jobId,
  progress,
  info,
  busy,
  metricConfirmed,
  hasPreview,
  onCancel,
  onRetry,
}: {
  jobId: string;
  progress: JobProgress | null;
  info: SceneInfo | null;
  busy: boolean;
  metricConfirmed: boolean;
  hasPreview: boolean;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const now = useNow(progress?.status === "RUNNING" || progress?.status === "QUEUED");
  const [section, setSection] = useState<"stages" | "compare">("stages");
  const views: StageView[] =
    progress?.stages.map((stage) => ({
      stage_id: stage.stage_id,
      state: stage.state,
      error: stage.error,
      fraction: null,
      // Bước tỉ lệ mét gồm thời gian chờ người chọn điểm (có khi hàng giờ): không hiện như thời gian máy chạy.
      seconds:
        stage.stage_id === "ST-METRIC-CANONICALIZE"
          ? null
          : stageSeconds(stage.started_at, stage.completed_at, stage.state === "running" ? now : null),
    })) ?? [];
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6">
      <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
        <div className="space-y-4">
          <StatusPanel progress={progress} now={now} />
          {info?.videoName && (
            <Card className="p-4 text-sm text-ink-muted">
              Video gốc: <span className="font-medium text-ink">{info.videoName}</span>
              {info.videoSize !== null && ` · ${formatBytes(info.videoSize)}`}
            </Card>
          )}
          {!hasPreview && progress?.stages.some((stage) => stage.stage_id === "ST-FRAME-EXTRACT" && stage.state === "succeeded") && (
            <Card className="overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element -- JPEG nhỏ do API tạo */}
              <img
                src={`/api/v1/jobs/${encodeURIComponent(jobId)}/thumbnail.jpg`}
                alt="Khung hình đầu của video"
                className="aspect-video w-full object-cover"
                onError={(event) => event.currentTarget.parentElement?.setAttribute("hidden", "")}
              />
              <p className="px-4 py-3 text-xs text-ink-muted">Khung hình đầu đã tách. Kết quả từng bước xem được khi bản xem 3DGS dựng xong.</p>
            </Card>
          )}
        </div>
        <Card className="h-fit p-5 sm:p-6">
          {progress ? (
            <PipelineTimeline
              stages={views}
              stageList={STUDIO_STAGES}
              timeNote={`Bước gần nhất đổi lúc ${new Date(progress.updated_at).toLocaleTimeString("vi-VN")}`}
            />
          ) : (
            <p className="flex items-center gap-2 text-sm text-ink-muted" role="status">
              <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
              Đang tải tiến trình…
            </p>
          )}
          <div className="mt-6 flex justify-end gap-2">
            {(progress?.status === "RUNNING" || progress?.status === "QUEUED") && progress.waiting_for === null && (
              <Button variant="danger" size="sm" disabled={busy} onClick={onCancel}>
                <Square aria-hidden />
                Huỷ xử lý
              </Button>
            )}
            {progress?.status === "FAILED" && (
              <Button size="sm" disabled={busy} onClick={onRetry}>
                <RotateCcw aria-hidden />
                Thử lại
              </Button>
            )}
          </div>
        </Card>
      </div>
      {hasPreview && (
        <section className="space-y-3">
          <div className="flex items-center gap-1" role="group" aria-label="Kết quả của pipeline">
            <ModeButton active={section === "stages"} onClick={() => setSection("stages")}>
              Kết quả từng bước
            </ModeButton>
            {metricConfirmed && (
              <ModeButton active={section === "compare"} onClick={() => setSection("compare")}>
                So sánh 3 hướng đo tỉ lệ
              </ModeButton>
            )}
          </div>
          <div className="h-[70vh] overflow-hidden rounded-xl border border-line">
            {section === "compare" && metricConfirmed ? <ModeComparisonView jobId={jobId} /> : <StageViewer jobId={jobId} />}
          </div>
        </section>
      )}
    </div>
  );
}

function StatusPanel({ progress, now }: { progress: JobProgress | null; now: number }) {
  if (!progress) return <Card className="h-32 animate-pulse motion-reduce:animate-none" />;
  if (progress.status === "QUEUED") {
    return (
      <Notice tone="ochre" icon={<Clock aria-hidden />}>
        <p className="font-medium text-ink">Đang chờ worker GPU nhận job</p>
        <p className="mt-1">Job đã vào hàng đợi; các job chạy lần lượt trên một GPU.</p>
      </Notice>
    );
  }
  if (progress.status === "FAILED") {
    return (
      <Notice tone="rust">
        <p className="font-medium">Xử lý thất bại</p>
        <p className="mt-1">{progress.error?.human_message ?? "Worker dừng trước khi hoàn tất."} Video gốc và kết quả các bước đã xong vẫn được giữ.</p>
      </Notice>
    );
  }
  if (progress.status === "CANCELLED") return <Notice>Đã huỷ xử lý scene này.</Notice>;
  if (progress.status === "SUCCEEDED") {
    return (
      <Notice tone="ember" icon={<Check aria-hidden />}>
        <p className="font-medium text-ink">Đã dựng xong scene</p>
        <p className="mt-1">Tiếp theo: xác nhận vật thể trong Studio, rồi tạo gói mô phỏng ở tab Kiểm tra & duyệt.</p>
      </Notice>
    );
  }
  if (progress.waiting_for === "metric_confirmation") {
    return (
      <Notice tone="ochre" icon={<Ruler aria-hidden />}>
        <p className="font-medium text-ink">Cần bạn xác nhận tỉ lệ mét</p>
        <p className="mt-1">Bản xem 3DGS chưa có đơn vị mét. Chọn điểm trên vật biết kích thước để hệ thống dựng tiếp collision.</p>
      </Notice>
    );
  }
  const elapsed = Math.max(0, (now - Date.parse(progress.started_at)) / 1000);
  return (
    <Card className="p-5 sm:p-6">
      <p className="text-sm font-medium">Đang xử lý trên máy chủ</p>
      <p className="mt-1 text-sm text-ink-muted">
        Có thể đóng trang; job vẫn chạy. Lần chạy này đã {Math.floor(elapsed / 60)} phút {Math.floor(elapsed % 60)} giây.
      </p>
    </Card>
  );
}

// ── Studio ──────────────────────────────────────────────────────────────────

function StudioTab({
  jobId,
  title,
  preview,
  mode,
  geometry,
  sceneReady,
  onSaveState,
  onMetricClose,
  onMetricConfirmed,
}: {
  jobId: string;
  title: string;
  preview: Preview;
  mode: StudioMode;
  geometry: StageState;
  sceneReady: boolean;
  onSaveState: (state: SaveState) => void;
  onMetricClose: () => void;
  onMetricConfirmed: () => void;
}) {
  if (mode === "metric") {
    return (
      <MetricConfirmView jobId={jobId} contentUrl={preview.url} filename={preview.filename} onClose={onMetricClose} onConfirmed={onMetricConfirmed} />
    );
  }
  if (mode === "gaussian") {
    return (
      <div className="flex h-full flex-col">
        <p className="border-b border-line bg-paper px-4 py-1.5 text-xs text-ink-muted">
          Chỉnh Gaussian trong SuperSplat: thay đổi chỉ nằm trong phiên editor và xuất ra file (File › Export PLY/SOG); không lưu vào scene, không qua duyệt.
        </p>
        <div className="min-h-0 flex-1">
          <EditorFrame contentUrl={preview.url} filename={preview.filename} homeHref="/" title={`Editor 3D: ${title}`} />
        </div>
      </div>
    );
  }
  if (sceneReady) return <ObjectReviewView jobId={jobId} onSaveState={onSaveState} />;
  return (
    <div className="flex h-full flex-col">
      <Notice tone={geometry === "failed" ? "rust" : "ochre"} className="m-3">
        {geometry === "running"
          ? "Đang dựng collision và tách vật thể; Studio vật thể mở khi xong. Tạm thời xem bản 3DGS bên dưới."
          : geometry === "failed"
            ? "Bước dựng collision lỗi — xem tab Tiến trình và bấm Thử lại."
            : "Bản xem 3DGS (chưa quy đổi mét). Studio vật thể mở sau khi xác nhận tỉ lệ và dựng collision."}
      </Notice>
      <div className="min-h-0 flex-1">
        <EditorFrame contentUrl={preview.url} filename={preview.filename} homeHref="/" title={`Editor 3D: ${title}`} />
      </div>
    </div>
  );
}

// ── Kiểm tra & duyệt ───────────────────────────────────────────────────────

function ReviewTab({ jobId, onSaveState }: { jobId: string; onSaveState: (state: SaveState) => void }) {
  const [revision, setRevision] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getJobScene(jobId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setRevision(result.data.scene.scene_revision);
        // Tạo gói ghi một revision mới (collider vật đã xác nhận) → header phải theo revision đó.
        onSaveState({ status: "saved", revision: result.data.scene.scene_revision });
      } else setError(result.error.detail);
    });
    return () => controller.abort();
  }, [jobId, reload, onSaveState]);
  if (error) return <Notice tone="rust" className="m-4">{error}</Notice>;
  if (!revision) return <p className="p-6 text-sm text-ink-muted" role="status">Đang tải scene…</p>;
  return (
    <div className="mx-auto grid max-w-5xl gap-4 px-4 py-6 sm:px-6 lg:grid-cols-2">
      <Card className="overflow-hidden">
        <SimulationPackagePanel jobId={jobId} sceneRevision={revision} onSceneChanged={() => setReload((value) => value + 1)} />
      </Card>
      <Card className="overflow-hidden">
        <ReviewPanel jobId={jobId} sceneRevision={revision} />
      </Card>
      <Notice icon={<Info aria-hidden />} className="lg:col-span-2">
        Mọi thay đổi vật thể sau khi tạo gói sẽ sinh revision mới: gói, báo cáo validation và quyết định duyệt cũ không còn áp dụng
        cho revision đó.
      </Notice>
    </div>
  );
}

// ── Kết quả ────────────────────────────────────────────────────────────────

function ResultsTab({ jobId, preview }: { jobId: string; preview: Preview }) {
  const [pkg, setPkg] = useState<SimulationPackageView | null>(null);
  const [review, setReview] = useState<ReviewStateView | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    // Scene chưa có SceneIR (chưa tách vật thể) thì hai lời gọi này lỗi — hiển thị "chưa có".
    getSimulationPackage(jobId, controller.signal).then(setPkg, () => setPkg(null));
    getReviewState(jobId, controller.signal).then(setReview, () => setReview(null));
    return () => controller.abort();
  }, [jobId]);
  const released = review?.record.status === "RELEASED";
  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-6 sm:px-6">
      <ResultCard
        icon={<Pencil aria-hidden />}
        title="Bản làm việc 3DGS"
        badge={<Badge tone="neutral">Chưa quy đổi mét · chưa duyệt</Badge>}
        body="Bản xem Brush (SOG) dùng để xem/chỉnh. Muốn xuất PLY/SOG đã chỉnh, mở Studio › Chỉnh Gaussian › File › Export."
        action={
          <a href={preview.url} download={preview.filename} className={buttonVariants({ variant: "secondary", size: "sm" })}>
            <Download aria-hidden /> Tải {preview.filename}
          </a>
        }
      />
      <ResultCard
        icon={<ClipboardCheck aria-hidden />}
        title="Gói mô phỏng (candidate)"
        badge={pkg?.package_ref ? <Badge tone="ochre">{pkg.scene_revision} · đã qua preflight, chưa validation</Badge> : <Badge tone="neutral">Chưa có</Badge>}
        body="OpenUSD (scene.usda + collider môi trường) của đúng revision hiện tại, để chạy kiểm tra trong Isaac Sim. Không phải bản phát hành."
        action={
          pkg?.package_ref ? (
            <a href={simulationPackageDownloadUrl(jobId)} className={buttonVariants({ variant: "secondary", size: "sm" })}>
              <Download aria-hidden /> Tải gói
            </a>
          ) : null
        }
      />
      <ResultCard
        icon={<ShieldCheck aria-hidden />}
        title="Bản phát hành"
        badge={released ? <Badge tone="sage">Đã phát hành</Badge> : <Badge tone="neutral">Chưa phát hành</Badge>}
        body={
          released
            ? "Gói đã validation và được Reviewer duyệt, kèm release manifest, báo cáo validation và bản ghi duyệt."
            : review?.blockers[0] ?? "Chỉ có sau khi gói qua validation Isaac và được Reviewer duyệt."
        }
        action={
          released ? (
            <a href={releaseDownloadUrl(jobId)} className={buttonVariants({ size: "sm" })}>
              <Download aria-hidden /> Tải bản phát hành
            </a>
          ) : null
        }
      />
    </div>
  );
}

function ResultCard({ icon, title, badge, body, action }: { icon: ReactNode; title: string; badge: ReactNode; body: string; action: ReactNode }) {
  return (
    <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center">
      <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper-sunken text-ink-muted [&_svg]:size-5">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 font-medium">
          {title} {badge}
        </p>
        <p className="mt-1 text-sm text-ink-muted">{body}</p>
      </div>
      {action}
    </Card>
  );
}

/** Revision SceneIR + trạng thái lưu (Q5): không có nút "Lưu nháp", mỗi thao tác tự lưu. */
function SaveStatus({ state }: { state: SaveState }) {
  if (state.status === "saving") {
    return (
      <Badge tone="neutral">
        <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />
        {state.revision} · Đang lưu…
      </Badge>
    );
  }
  if (state.status === "error") {
    return (
      <span className="flex items-center gap-1.5" role="alert">
        <Badge tone="rust" title={state.message}>
          <TriangleAlert aria-hidden />
          {state.revision} · Lưu lỗi
        </Badge>
        <Button size="sm" variant="ghost" onClick={state.retry}>
          Thử lại
        </Button>
      </span>
    );
  }
  return (
    <Badge tone="neutral" title="Mỗi thao tác trên vật thể được lưu thành một revision mới">
      <Check aria-hidden />
      {state.revision} · đã lưu
    </Badge>
  );
}

// ── Trạng thái phụ ───────────────────────────────────────────────────────────

type StageState = "none" | "running" | "succeeded" | "failed";

function stageState(progress: JobProgress | null, stageId: string): StageState {
  const stage = progress?.stages.find((item) => item.stage_id === stageId);
  if (stage?.state === "running") return "running";
  if (stage?.state === "succeeded") return "succeeded";
  if (stage?.state === "failed") return "failed";
  return "none";
}

function metricState(progress: JobProgress | null): "waiting" | "confirmed" | "none" {
  if (progress?.waiting_for === "metric_confirmation") return "waiting";
  return stageState(progress, "ST-METRIC-CANONICALIZE") === "succeeded" ? "confirmed" : "none";
}

function MetricBadge({ state }: { state: "waiting" | "confirmed" | "none" }) {
  return state === "confirmed" ? (
    <Badge tone="sage">
      <Check aria-hidden />
      Đã xác nhận tỉ lệ mét
    </Badge>
  ) : (
    <Badge tone="ochre" title="Preview dựng từ ảnh có đơn vị tuỳ ý; cần xác nhận tỉ lệ mét trước khi dựng hình học">
      <Info aria-hidden />
      Chưa quy đổi mét
    </Badge>
  );
}

function GeometryBadge({ state }: { state: StageState }) {
  if (state === "running") {
    return (
      <Badge tone="ember">
        <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />
        Đang dựng collision
      </Badge>
    );
  }
  if (state === "succeeded") {
    return (
      <Badge tone="sage">
        <Box aria-hidden />
        Đã có collision mesh
      </Badge>
    );
  }
  if (state === "failed") {
    return (
      <Badge tone="rust">
        <TriangleAlert aria-hidden />
        Dựng collision lỗi
      </Badge>
    );
  }
  return null;
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
