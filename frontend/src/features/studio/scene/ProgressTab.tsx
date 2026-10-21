"use client";

import { Square } from "lucide-react";
import { Button, Notice, ProgressBar } from "@/components/studio/primitives";
import { HelpDetails } from "@/components/studio/feedback";
import { PipelineTimeline, type StageAction, type TimelineStageView } from "@/features/studio/PipelineTimeline";
import { runtimeWaitText } from "@/features/studio/sceneStatus";
import { isJobStale, stageSeconds, useNow, type SceneInfo } from "@/features/studio/scene/state";
import { GEOMETRY_REVIEW_STAGE, GEOMETRY_REVIEW_STAGE_ID, stagesFor, type TimelineStageMeta } from "@/features/studio/stages";
import { AnonymizationReviewPanel } from "@/features/studio/scene/AnonymizationReviewPanel";
import { AttemptHistory } from "@/features/studio/scene/AttemptHistory";
import { ProgressFrame } from "@/features/studio/scene/ProgressFrame";
import { useObjectify } from "@/features/studio/scene/objectifyContext";
import { timelineFromSteps } from "@/features/studio/scene/pipeline";
import { usePipelineView } from "@/features/studio/scene/pipelineContext";
import { stepActions } from "@/features/studio/scene/stepActions";
import { GpuStartupNotice } from "@/features/studio/GpuStartupNotice";
import { geometryReviewStep, objectifyStageOverride, type GeometryStep } from "@/features/studio/scene/useObjectify";
import { QueueStatus } from "@/features/studio/scene/QueueStatus";
import { ResourceWaitDetail } from "@/features/studio/scene/ResourceWaitDetail";
import type { JobProgress } from "@/lib/contracts/studio";
import { formatBytes } from "@/lib/format";
import { geometryPhaseLabel } from "@/lib/scene/geometry-state";

const ANONYMIZATION_PANEL_ID = "anonymization-review-panel";

/** Phụ đề của hàng "Duyệt vật & Tạo mesh" theo trạng thái (T-021). */
function geometryNote(step: GeometryStep): string | undefined {
  if (step.state === "running") return step.cancelling ? "Đang dừng…" : (geometryPhaseLabel(step.phase) ?? "Đang xếp hàng");
  if (step.state === "waiting") return "Chỉnh vùng nếu cần, rồi Tạo mesh";
  if (step.state === "failed") return step.error ?? "Tạo mesh chưa xong.";
  if (step.rebuildFailed) return `Dựng lại vùng thất bại; scene giữ bản trước. ${step.error ?? ""}`.trim();
  return undefined;
}

/** Tiến trình chỉ quản lý trạng thái; viewer mở qua route giai đoạn riêng. */
export function ProgressTab({ jobId, progress, info, busy, canCancel, canAccept = canCancel, onCancel, onChanged, onConfirmMetric, onOpenStudio, onRetry, retryDisabled = false, retryHint }: {
  jobId: string; progress: JobProgress | null; info: SceneInfo | null; busy: boolean; canCancel: boolean; canAccept?: boolean; onCancel: () => void; onChanged?: () => void;
  /** Mở Studio ở chế độ scene để duyệt hoặc sửa vùng; undefined khi người xem không có quyền thao tác trên job. */
  onOpenStudio?: () => void;
  /** Mở công cụ xác nhận tỉ lệ mét; undefined khi người xem không có quyền thao tác trên job. */
  onConfirmMetric?: () => void;
  /** Tạo lượt chạy mới cho bước lỗi; undefined khi backend chưa cho thử lại hoặc người xem không có quyền. */
  onRetry?: () => void;
  retryDisabled?: boolean;
  retryHint?: string;
}) {
  const reviewing = progress?.waiting_for === "anonymization_review";
  const pipelineView = usePipelineView();
  const now = useNow((progress?.status === "RUNNING" || progress?.status === "QUEUED") && !progress?.waiting_for);
  const stale = isJobStale(progress, now);
  // Bước "Tách vật thể" luôn ghi thành công vì scene đã được tạo; nếu tách theo vật lỗi hết số lần thử thì hàng bước đó
  // phải báo lỗi và có nút chọn tiếp tại chỗ, không chỉ trong màn chi tiết vật thể.
  const objectStageDone = progress?.stages.some((stage) => stage.stage_id === "ST-OBJECT-EXTRACT" && stage.state === "succeeded") ?? false;
  const objectify = useObjectify({ jobId, enabled: objectStageDone, onRevision: () => onChanged?.() });
  const objectOverride = objectStageDone ? objectifyStageOverride(objectify.state) : null;
  const views: TimelineStageView[] = progress?.stages.map((stage) => stage.stage_id === "ST-OBJECT-EXTRACT" && objectOverride
    ? { stage_id: stage.stage_id, state: objectOverride.state, error: objectOverride.error, fraction: null, seconds: null, note: stage.note }
    : {
      stage_id: stage.stage_id, state: stage.state, error: stage.error, fraction: null, note: stage.note,
      seconds: stage.stage_id === "ST-METRIC-CANONICALIZE" ? null : stageSeconds(stage.started_at, stage.completed_at, stage.state === "running" ? now : null),
    }) ?? [];
  // Hàng ảo "Duyệt vật & Tạo mesh" (T-021): chỉ khi scene có khoá object_geometry và tách vật đã xong.
  const geometry = objectStageDone ? geometryReviewStep(objectify.state) : null;
  const timelineViews: TimelineStageView[] = geometry
    ? [...views, { stage_id: GEOMETRY_REVIEW_STAGE_ID, state: geometry.state, seconds: null, fraction: null, note: [geometryNote(geometry), objectify.state?.geometry_note].filter(Boolean).join(" · ") || null }]
    : views;
  const apiStageList: readonly TimelineStageMeta[] = progress ? stagesFor(progress.stages.map((stage) => stage.stage_id)) : [];
  const objectIndex = apiStageList.findIndex((meta) => meta.id === "ST-OBJECT-EXTRACT");
  const stageList: readonly TimelineStageMeta[] = geometry && objectIndex >= 0
    ? [...apiStageList.slice(0, objectIndex + 1), GEOMETRY_REVIEW_STAGE, ...apiStageList.slice(objectIndex + 1)]
    : apiStageList;
  // Mọi thao tác người dùng cần làm đều có nút ngay ở hàng của bước đang chờ, không dùng khung thông báo riêng.
  const stageActions: StageAction[] = [];
  if (geometry && canAccept) {
    if (geometry.state === "running") {
      if (!geometry.cancelling) {
        stageActions.push({ stageId: GEOMETRY_REVIEW_STAGE_ID, label: "Hủy yêu cầu", onClick: () => void objectify.cancel(), disabled: objectify.sending });
      }
    } else if (geometry.state === "failed") {
      if (onOpenStudio) stageActions.push({ stageId: GEOMETRY_REVIEW_STAGE_ID, label: "Mở để sửa vùng", onClick: onOpenStudio });
      stageActions.push({
        stageId: GEOMETRY_REVIEW_STAGE_ID,
        label: "Thử lại Tạo mesh",
        onClick: () => void objectify.send("geometry", objectify.state?.scene_revision ?? undefined),
        disabled: objectify.sending,
      });
    } else if (geometry.state === "waiting" && onOpenStudio) {
      stageActions.push({ stageId: GEOMETRY_REVIEW_STAGE_ID, label: "Mở để duyệt", onClick: onOpenStudio });
    } else if (geometry.rebuildFailed && onOpenStudio) {
      stageActions.push({ stageId: GEOMETRY_REVIEW_STAGE_ID, label: "Mở Studio", onClick: onOpenStudio });
    }
  }
  if (progress?.waiting_for === "metric_confirmation" && onConfirmMetric) {
    stageActions.push({ stageId: "ST-METRIC-CANONICALIZE", label: "Xác nhận tỉ lệ mét", onClick: onConfirmMetric });
  }
  if (onRetry && progress?.status === "FAILED" && progress.error?.retryable && progress.error.stage_id) {
    stageActions.push({ stageId: progress.error.stage_id, label: "Thử lại", onClick: onRetry, disabled: retryDisabled, hint: retryHint });
  }
  if (objectOverride && canAccept) {
    if (objectOverride.state === "running") {
      if (!objectify.state?.cancellation_requested) {
        stageActions.push({ stageId: "ST-OBJECT-EXTRACT", label: "Hủy yêu cầu", onClick: () => void objectify.cancel(), disabled: objectify.sending });
      }
    } else {
      if (objectify.state?.available && objectify.state.retryable !== false) {
        stageActions.push({ stageId: "ST-OBJECT-EXTRACT", label: "Chạy lại tách theo vật", onClick: () => void objectify.send("objectify"), disabled: objectify.sending });
      }
      stageActions.push({ stageId: "ST-OBJECT-EXTRACT", label: "Dùng hộp ứng viên", onClick: () => void objectify.send("boxes"), disabled: objectify.sending });
    }
  }
  if (reviewing && progress?.current_stage) {
    stageActions.push({
      stageId: progress.current_stage,
      label: "Xem bản đã che",
      onClick: () => document.getElementById(ANONYMIZATION_PANEL_ID)?.scrollIntoView({ behavior: "smooth", block: "start" }),
    });
  }
  // T-061: trong trang scene, dòng tiến trình vẽ từ bước thật của backend và nút đến từ `next_action`.
  const fromPipeline = pipelineView ? timelineFromSteps(pipelineView, now) : null;
  const shownStages = fromPipeline?.stages ?? timelineViews;
  const shownList = fromPipeline?.stageList ?? stageList;
  const shownActions = pipelineView
    ? stepActions(
        pipelineView,
        {
          confirmMetric: onConfirmMetric,
          openStudio: onOpenStudio,
          showAnonymization: () => document.getElementById(ANONYMIZATION_PANEL_ID)?.scrollIntoView({ behavior: "smooth", block: "start" }),
          retryJob: onRetry,
          ...(canAccept
            ? {
                retryGeometry: () => void objectify.send("geometry", pipelineView.scene_revision ?? undefined),
                cancelOperation: () => void objectify.cancel(),
                rerunObjectify: () => void objectify.send("objectify"),
                useBoxes: () => void objectify.send("boxes"),
              }
            : {}),
        },
        objectify.sending,
        { retryDisabled, retryHint },
      )
    : stageActions;
  return <div className="mx-auto max-w-5xl space-y-4 px-4 py-6 sm:px-6">
    <ProgressFrame hint="Bấm tên bước đã xong để xem kết quả.">
      {reviewing && <div id={ANONYMIZATION_PANEL_ID} className="scroll-mt-4"><AnonymizationReviewPanel key={jobId + ":" + progress.attempt} jobId={jobId} canAccept={canAccept} onAccepted={() => onChanged?.()} /></div>}
      {!reviewing && (progress?.status === "QUEUED" || progress?.waiting_for === "resources" || progress?.queue) && <div role="status" className="mb-5 space-y-2 text-sm text-ink-muted">
        <p>{progress.waiting_for === "runtime"
          ? runtimeWaitText(progress)
          : progress.waiting_for === "resources" ? "Đang chờ máy xử lý đủ tài nguyên." : "Đang xếp hàng chờ máy xử lý."} Scene tự chạy khi đến lượt.</p>
        <ProgressBar value={null} label="Đang chờ trong hàng đợi" />
        {progress.queue && <QueueStatus queue={progress.queue} />}
        {pipelineView?.gpu && <GpuStartupNotice capacity={pipelineView.gpu} />}
        {progress.waiting_for === "resources" && progress.resource_wait && <ResourceWaitDetail wait={progress.resource_wait} />}
      </div>}
      {objectify.error && objectOverride && <Notice tone="rust" className="mb-4">{objectify.error}</Notice>}
      {progress ? (
        <>
          <PipelineTimeline stageActions={shownActions} stages={shownStages} stageList={shownList} jobId={jobId} isStale={stale} timeNote={"Cập nhật lúc " + new Date(progress.updated_at).toLocaleTimeString("vi-VN") + (stale ? " · Tiến trình mất kết nối" : progress.status === "RUNNING" || progress.status === "QUEUED" ? " · Có thể đóng trang, scene vẫn chạy" : "")} />
        </>
      ) : <p role="status" className="text-sm text-ink-muted">Đang tải tiến trình…</p>}
      {canCancel && <div className="mt-4 flex justify-end gap-3">
        <Button variant="danger" size="sm" disabled={busy} onClick={onCancel}><Square aria-hidden />Huỷ xử lý</Button>
      </div>}
    </ProgressFrame>
    {progress && <AttemptHistory jobId={jobId} attempt={progress.attempt} status={progress.status} />}
    <HelpDetails title="Đầu vào và cách theo dõi">
      {info?.videoName && <p>Video gốc: {info.videoName}{info.videoSize !== null ? " · " + formatBytes(info.videoSize) : ""}</p>}
      {info?.displayVideoUrl && <figure className="max-w-2xl">
        <video src={info.displayVideoUrl} controls muted playsInline preload="metadata" className="mt-2 aspect-video w-full rounded-xl bg-viewport" />
        <figcaption className="mt-1.5 text-xs text-ink-muted">Video ghép từ ảnh gốc, chỉ để xem lại</figcaption>
      </figure>}
      {info?.createdBy && <p>Scene do {info.createdBy} tạo.</p>}
      <p>Scene vẫn chạy khi bạn rời trang. Bước tỉ lệ mét cần bạn thao tác trong Studio.</p>
      <p>Thời gian chờ bạn thao tác không tính vào thời gian xử lý.</p>
    </HelpDetails>
  </div>;
}
