"use client";

import { Square } from "lucide-react";
import { Button, Notice, ProgressBar } from "@/components/studio/primitives";
import { HelpDetails } from "@/components/studio/feedback";
import { PipelineTimeline, type StageAction, type StageView, type TimelineStageView } from "@/features/studio/PipelineTimeline";
import { isJobStale, stageSeconds, useNow, type SceneInfo } from "@/features/studio/scene/state";
import { GEOMETRY_REVIEW_STAGE, GEOMETRY_REVIEW_STAGE_ID, stagesFor, type TimelineStageMeta } from "@/features/studio/stages";
import { AnonymizationReviewPanel } from "@/features/studio/scene/AnonymizationReviewPanel";
import { AttemptHistory } from "@/features/studio/scene/AttemptHistory";
import { ProgressFrame } from "@/features/studio/scene/ProgressFrame";
import { useObjectify } from "@/features/studio/scene/objectifyContext";
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
  const now = useNow(progress?.status === "RUNNING" || progress?.status === "QUEUED");
  const stale = isJobStale(progress, now);
  // Bước "Tách vật thể" luôn ghi thành công vì scene đã được tạo; nếu tách theo vật lỗi hết số lần thử thì hàng bước đó
  // phải báo lỗi và có nút chọn tiếp tại chỗ, không chỉ trong màn chi tiết vật thể.
  const objectStageDone = progress?.stages.some((stage) => stage.stage_id === "ST-OBJECT-EXTRACT" && stage.state === "succeeded") ?? false;
  const objectify = useObjectify({ jobId, enabled: objectStageDone, onRevision: () => onChanged?.() });
  const objectOverride = objectStageDone ? objectifyStageOverride(objectify.state) : null;
  const views: StageView[] = progress?.stages.map((stage) => stage.stage_id === "ST-OBJECT-EXTRACT" && objectOverride
    ? { stage_id: stage.stage_id, state: objectOverride.state, error: objectOverride.error, fraction: null, seconds: null }
    : {
      stage_id: stage.stage_id, state: stage.state, error: stage.error, fraction: null,
      seconds: stage.stage_id === "ST-METRIC-CANONICALIZE" ? null : stageSeconds(stage.started_at, stage.completed_at, stage.state === "running" ? now : null),
    }) ?? [];
  // Hàng ảo "Duyệt vật & Tạo mesh" (T-021): chỉ khi scene có khoá object_geometry và tách vật đã xong.
  const geometry = objectStageDone ? geometryReviewStep(objectify.state) : null;
  const timelineViews: TimelineStageView[] = geometry
    ? [...views, { stage_id: GEOMETRY_REVIEW_STAGE_ID, state: geometry.state, seconds: null, fraction: null, note: geometryNote(geometry) }]
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
  return <div className="mx-auto max-w-5xl space-y-4 px-4 py-6 sm:px-6">
    <ProgressFrame hint="Bấm tên bước đã xong để mở Xem giai đoạn; bước lỗi hoặc cần bạn thao tác có nút ngay tại bước đó.">
      {reviewing && <div id={ANONYMIZATION_PANEL_ID} className="scroll-mt-4"><AnonymizationReviewPanel key={jobId + ":" + progress.attempt} jobId={jobId} canAccept={canAccept} onAccepted={() => onChanged?.()} /></div>}
      {!reviewing && (progress?.status === "QUEUED" || progress?.waiting_for === "resources" || progress?.queue) && <div role="status" className="mb-5 space-y-2 text-sm text-ink-muted">
        <p>{progress.waiting_for === "runtime"
          ? "Đang chờ GPU: chưa có máy xử lý nào đang chạy đúng phiên bản công cụ của job này. Job tự chạy khi máy đó lên."
          : progress.waiting_for === "resources" ? "Đang chờ đủ tài nguyên trên máy xử lý." : "Job đã vào hàng đợi, đang chờ máy xử lý."} Cấu hình đã chọn được giữ nguyên; job tự chạy tiếp khi đến lượt và đủ tài nguyên.</p>
        <ProgressBar value={null} label="Đang chờ trong hàng đợi" />
        {progress.queue && <QueueStatus queue={progress.queue} />}
        {progress.waiting_for === "resources" && progress.resource_wait && <ResourceWaitDetail wait={progress.resource_wait} />}
      </div>}
      {objectify.error && objectOverride && <Notice tone="rust" className="mb-4">{objectify.error}</Notice>}
      {progress ? (
        <>
          <PipelineTimeline stageActions={stageActions} stages={timelineViews} stageList={stageList} jobId={jobId} isStale={stale} timeNote={"Cập nhật lúc " + new Date(progress.updated_at).toLocaleTimeString("vi-VN") + (stale ? " · Tiến trình mất kết nối" : progress.status === "RUNNING" || progress.status === "QUEUED" ? " · Có thể đóng trang, job tiếp tục chạy trên máy chủ" : "")} />
        </>
      ) : <p role="status" className="text-sm text-ink-muted">Đang tải tiến trình…</p>}
      {canCancel && <div className="mt-4 flex justify-end gap-3">
        <Button variant="danger" size="sm" disabled={busy} onClick={onCancel}><Square aria-hidden />Huỷ xử lý</Button>
      </div>}
    </ProgressFrame>
    {progress && <AttemptHistory jobId={jobId} attempt={progress.attempt} status={progress.status} />}
    <HelpDetails title="Đầu vào và cách theo dõi">
      {info?.videoName && <p>Video gốc: {info.videoName}{info.videoSize !== null ? " · " + formatBytes(info.videoSize) : ""}</p>}
      {info?.createdBy && <p>Scene do {info.createdBy} tạo.</p>}
      <p>Job vẫn chạy khi bạn rời trang. Bước tỉ lệ mét cần thao tác của bạn trong Studio; view giai đoạn 6 chỉ mở sau khi bước này hoàn tất.</p>
      <p>Thời gian từng bước lấy từ API; thời gian chờ bạn xác nhận không được trình bày như thời gian máy xử lý.</p>
    </HelpDetails>
  </div>;
}
