"use client";

import { errorMessage } from "@/lib/ui-error";
import { GAUSSIAN_EDIT_ENABLED } from "@/features/studio/scene/state";

import { ArrowLeft, Download, Info, Loader2 } from "lucide-react";
import dynamic from "next/dynamic";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useEffect, useState } from "react";

import { Badge, Button, Card, Notice } from "@/components/studio/primitives";
import { usePageTitle } from "@/features/shell/Breadcrumbs";
import { canInspect, inspectHref, inspectionStage, progressHref } from "@/features/studio/inspection";
import {
  LIDAR_CALIBRATION_QA_STAGE,
  LIDAR_ODOMETRY_STAGE,
  LIDAR_STAGE,
  STUDIO_STAGES,
  stagesFor,
} from "@/features/studio/stages";
import { getJob, getProject, jobArtifactContentUrl, listJobArtifacts } from "@/lib/api/endpoints";
import { StageMetrics } from "@/features/studio/evaluation/EvaluationCard";
import { getJobProgress } from "@/lib/api/studio";
import type { JobManifest, ProductArtifactRef, Project, StageId } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";
import { formatBytes } from "@/lib/format";
import { LidarCalibrationQAStage } from "@/features/studio/inspection/LidarCalibrationQAStage";
import { LidarOdometryStage } from "@/features/studio/inspection/LidarOdometryStage";

const SceneWorkspace = dynamic(() => import("@/features/studio/inspection/StageSceneWorkspace").then((m) => m.StageSceneWorkspace), { ssr: false, loading: () => <Loading /> });
const StageViewer = dynamic(() => import("@/features/studio/StageViewer").then((m) => m.StageViewer), { ssr: false, loading: () => <Loading /> });

interface Snapshot {
  progress: JobProgress;
  job: JobManifest | null;
  project: Project | null;
  artifacts: ProductArtifactRef[];
  warnings: string[];
}

/** Một workspace đầy màn hình, tám nội dung; không fetch output trước gate completed. */
export function StageInspectionPage({ jobId, stageId }: { jobId: string; stageId: string }) {
  const meta = inspectionStage(stageId);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [details, setDetails] = useState(false);
  usePageTitle(snapshot?.project?.name ?? null);

  useEffect(() => {
    if (!meta) return;
    const controller = new AbortController();
    // T-065: tải sẵn mã khung xem song song với request đầu, không chờ cổng "đã xong" mới bắt đầu tải chunk.
    if (meta.id === LIDAR_STAGE.id || meta.id === "ST-FRAME-EXTRACT" || meta.id === "ST-CAMERA-POSE") void import("@/features/studio/StageViewer").catch(() => undefined);
    else if (meta.id !== "ST-INPUT-VALIDATE" && meta.id !== "ST-PRIVACY-GATE") void import("@/features/studio/inspection/StageSceneWorkspace").catch(() => undefined);
    void (async () => {
      try {
        const progress = await getJobProgress(jobId, controller.signal);
        if (controller.signal.aborted) return;
        if (!progress.ok) { setError(errorMessage(progress.error)); return; }
        if (!canInspect(progress.data, meta.id)) {
          setSnapshot({ progress: progress.data, job: null, project: null, artifacts: [], warnings: [] });
          return;
        }
        const [job, artifacts] = await Promise.all([getJob(jobId), listJobArtifacts(jobId)]);
        if (controller.signal.aborted) return;
        const uris = new Set(job.ok ? job.data.stage_artifacts.filter((stage) => stage.stage_id === meta.id).map((stage) => stage.artifact_uri) : []);
        const warnings = [!job.ok && `Job: ${errorMessage(job.error)}`, !artifacts.ok && `Artifact: ${errorMessage(artifacts.error)}`].filter((value): value is string => Boolean(value));
        setSnapshot({
          progress: progress.data, job: job.ok ? job.data : null,
          project: null,
          artifacts: artifacts.ok ? artifacts.data.artifacts.filter((ref) => ref.producer_stage === meta.id || uris.has(ref.artifact_uri)) : [],
          warnings,
        });
        // T-065: tên dự án chỉ cho tiêu đề; về sau thì điền vào, không chặn viewer.
        if (!job.ok) return;
        const project = await getProject(job.data.project_id);
        if (controller.signal.aborted) return;
        setSnapshot((previous) => previous && {
          ...previous,
          project: project.ok ? project.data : null,
          warnings: project.ok ? previous.warnings : [...previous.warnings, `Project: ${errorMessage(project.error)}`],
        });
      } catch (cause) {
        if (!controller.signal.aborted) setError(errorMessage(cause, "Không tải được giai đoạn"));
      }
    })();
    return () => controller.abort();
  }, [jobId, meta, reload]);

  function retry() {
    setSnapshot(null);
    setError(null);
    setReload((value) => value + 1);
  }

  if (!meta) return <Notice tone="rust" className="m-6">Giai đoạn không thuộc pipeline Studio.</Notice>;
  const pageStages = snapshot ? stagesFor(snapshot.progress.stages.map((stage) => stage.stage_id)) : STUDIO_STAGES;
  const index = Math.max(0, pageStages.findIndex((stage) => stage.id === meta.id));
  const ready = snapshot && canInspect(snapshot.progress, meta.id);
  const failedQA = meta.id === LIDAR_CALIBRATION_QA_STAGE.id && (snapshot?.progress.stages.some(
    (stage) => stage.stage_id === LIDAR_CALIBRATION_QA_STAGE.id && stage.state === "failed",
  ) ?? false);
  return (
    <main className="flex h-[calc(100dvh-3rem)] min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-line bg-paper-raised px-4 py-3">
        <Link href={progressHref(jobId)} className="inline-flex items-center gap-1 text-sm text-ember-strong hover:underline"><ArrowLeft className="size-4" aria-hidden /> Về Tiến trình</Link>
        <div className="min-w-0 flex-1"><h1 className="truncate font-bold">{index + 1}. {meta.title}</h1><p className="truncate text-xs text-ink-muted">{snapshot?.project?.name ?? jobId}</p></div>
        {ready && (failedQA ? <Badge tone="rust">QA thất bại</Badge> : <Badge tone="sage">Đã xử lý xong</Badge>)}
        {snapshot && <Badge tone="neutral">Lần chạy {snapshot.progress.attempt}</Badge>}
        {ready && <Button variant="ghost" size="sm" aria-expanded={details} aria-controls="stage-output-info" onClick={() => setDetails((value) => !value)}><Info aria-hidden /> Thông tin đầu ra</Button>}
      </header>
      <nav aria-label="Giai đoạn của scene" className="flex shrink-0 gap-1 overflow-x-auto border-b border-line bg-paper px-4 py-2">
        {pageStages.map((stage, n) => {
          const label = `${n + 1}. ${stage.short}`;
          return snapshot && canInspect(snapshot.progress, stage.id)
            ? <Link key={stage.id} href={inspectHref(jobId, stage.id)} aria-current={stage.id === meta.id ? "page" : undefined} className={`shrink-0 rounded-lg px-3 py-2 text-sm ${stage.id === meta.id ? "bg-ember-soft font-medium text-ember-strong" : "text-ink-muted hover:bg-paper-sunken"}`}>{label}</Link>
            : <span key={stage.id} aria-disabled="true" className="shrink-0 px-3 py-2 text-sm text-ink-subtle" title="Chỉ mở khi giai đoạn đã xong">{label}</span>;
        })}
      </nav>
      {error ? <Notice tone="rust" className="m-4">{error} <Button variant="secondary" size="sm" onClick={retry}>Thử lại</Button><Link href={`/login?next=${encodeURIComponent(inspectHref(jobId, meta.id))}`} className="ml-3 underline">Đăng nhập</Link></Notice>
        : !snapshot ? <Loading />
          : !ready ? <Notice tone="ochre" className="m-4">Giai đoạn này chưa hoàn tất trong lần chạy hiện tại. Quay về Tiến trình để theo dõi; xác nhận tỉ lệ khi đang chờ được thực hiện ở Studio.</Notice>
            : <>
              {snapshot.warnings.length > 0 && <Notice tone="rust" className="m-3">Chưa đọc đủ dữ liệu: {snapshot.warnings.join(" · ")} <Button size="sm" variant="secondary" onClick={retry}>Thử lại</Button></Notice>}
              <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
                <section aria-label={`Nội dung ${meta.title}`} className="relative min-h-0 min-w-0 flex-1 overflow-auto">
                  {meta.id === LIDAR_CALIBRATION_QA_STAGE.id
                    ? <LidarCalibrationQAStage jobId={jobId} artifacts={snapshot.artifacts} />
                    : meta.id === LIDAR_ODOMETRY_STAGE.id
                      ? <LidarOdometryStage jobId={jobId} artifacts={snapshot.artifacts} />
                    : meta.id === "ST-INPUT-VALIDATE" || meta.id === "ST-PRIVACY-GATE"
                      ? <InputStage stageId={meta.id} snapshot={snapshot} />
                      : meta.id === LIDAR_STAGE.id || meta.id === "ST-FRAME-EXTRACT" || meta.id === "ST-CAMERA-POSE"
                        ? <StageViewer jobId={jobId} stageId={meta.id} />
                        : <SceneWorkspace jobId={jobId} stageId={meta.id} title={snapshot.project?.name ?? "Scene"} />}
                </section>
                {details && <aside id="stage-output-info" aria-label="Thông tin đầu ra" className="max-h-[40vh] shrink-0 overflow-y-auto border-t border-line bg-paper-raised p-4 lg:max-h-none lg:w-80 lg:border-t-0 lg:border-l">
                  <StageMetrics jobId={jobId} groupId={meta.id} />
                  <h2 className="mt-6 font-bold">Đầu ra của giai đoạn</h2>
                  <p className="mt-2 text-sm leading-relaxed text-ink-muted">{meta.description}</p>
                  <p className="mt-3 text-xs text-ink-muted">Artifact đã publish là bất biến. {GAUSSIAN_EDIT_ENABLED ? "Chỉnh Gaussian xuất file riêng; chỉnh" : "Chỉnh"} vật thể tạo SceneIR revision mới.</p>
                  <p className="mt-3 text-xs text-ink-muted">Hoàn tất: {snapshot.progress.stages.find((stage) => stage.stage_id === meta.id)?.completed_at ? new Date(snapshot.progress.stages.find((stage) => stage.stage_id === meta.id)!.completed_at!).toLocaleString("vi-VN") : "Không có mốc thời gian"}</p>
                  <ul className="mt-4 space-y-4">{snapshot.artifacts.map((ref) => <li key={`${ref.artifact_uri}:${ref.artifact_checksum}`} className="space-y-1 border-t border-line pt-3"><p className="text-sm font-medium">{ref.artifact_type}</p><p className="break-all font-mono text-[10px] text-ink-subtle">{ref.artifact_checksum}</p><a href={jobArtifactContentUrl(jobId, ref)} download className="inline-flex items-center gap-1 text-sm text-ember-strong hover:underline"><Download className="size-4" aria-hidden /> Tải artifact</a></li>)}</ul>
                  {!snapshot.artifacts.length && <p className="mt-4 text-sm text-ink-muted">API chưa cung cấp artifact tải riêng cho bước này.</p>}
                </aside>}
              </div>
            </>}
    </main>
  );
}

function Loading() {
  return <p role="status" className="flex items-center justify-center gap-2 p-6 text-sm text-ink-muted"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang mở giai đoạn…</p>;
}

/** Dữ liệu đầu vào/privacy được đọc từ project, không suy thành quality report chưa có. */
function InputStage({ stageId, snapshot }: { stageId: StageId; snapshot: Snapshot }) {
  const project = snapshot.project;
  if (!project) return <Notice tone="ochre" className="m-4">Chưa đọc được thông tin đầu vào. Dùng Thử lại hoặc xem artifact của giai đoạn.</Notice>;
  const privacy = stageId === "ST-PRIVACY-GATE";
  const values = privacy ? [
    ["Kết quả privacy", project.privacy.result], ["Phạm vi kiểm tra", project.privacy.inspection_scope],
    ["Được dispatch", project.privacy.dispatch_allowed ? "Có" : "Không"], ["Lý do chặn", project.privacy.block_reason ?? "Không có"],
    ["Đã xác nhận quyền sử dụng", project.source_rights_attestation.rights_to_use_confirmed === true ? "Có" : "Chưa xác nhận"],
    ["Đã xác nhận ẩn danh", project.source_rights_attestation.anonymization_confirmed === true ? "Có" : "Chưa xác nhận"],
  ] : [
    ["Tên scene", project.name], ["Nguồn", project.source_type], ["Video", project.input_video?.original_name ?? "Không có metadata video"],
    ["Định dạng", project.input_video?.media_type ?? "Không có dữ liệu"], ["Dung lượng", project.input_video ? formatBytes(project.input_video.size_bytes) : "Không có dữ liệu"],
    ["Checksum đầu vào", project.input_manifest_checksum],
  ];
  return <div className="mx-auto max-w-3xl space-y-4 p-6"><Card className="p-5"><h2 className="text-lg font-bold tracking-tight">{privacy ? "Quyền riêng tư của đầu vào" : "Đầu vào đã kiểm tra"}</h2><dl className="mt-4 divide-y divide-line">{values.map(([label, value]) => <div key={label} className="grid gap-1 py-3 sm:grid-cols-[12rem_1fr]"><dt className="text-sm text-ink-muted">{label}</dt><dd className="break-all text-sm">{value}</dd></div>)}</dl></Card><Notice>{privacy ? "Xác nhận của người tải lên và kết quả QA là hai cơ chế riêng. Thông tin trên lấy từ project hiện tại; report chi tiết chỉ xem khi backend publish artifact." : "API hiện cung cấp metadata video và artifact của bước. Chưa có API summary cho từng chỉ số nhòe/chuyển động; không hiển thị số đo giả."}</Notice></div>;
}
