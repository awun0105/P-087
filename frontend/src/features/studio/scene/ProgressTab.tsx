"use client";

import { Square } from "lucide-react";
import { Button, Card, ProgressBar } from "@/components/studio/primitives";
import { HelpDetails } from "@/components/studio/feedback";
import { PipelineTimeline, type StageView } from "@/features/studio/PipelineTimeline";
import { isJobStale, stageSeconds, useNow, type SceneInfo } from "@/features/studio/scene/state";
import { stagesFor } from "@/features/studio/stages";
import { AnonymizationReviewPanel } from "@/features/studio/scene/AnonymizationReviewPanel";
import { AttemptHistory } from "@/features/studio/scene/AttemptHistory";
import { QueueStatus } from "@/features/studio/scene/QueueStatus";
import { ResourceWaitDetail } from "@/features/studio/scene/ResourceWaitDetail";
import type { JobProgress } from "@/lib/contracts/studio";
import { formatBytes } from "@/lib/format";

/** Tiến trình chỉ quản lý trạng thái; viewer mở qua route giai đoạn riêng. */
export function ProgressTab({ jobId, progress, info, busy, canCancel, canAccept = canCancel, onCancel, onChanged }: {
  jobId: string; progress: JobProgress | null; info: SceneInfo | null; busy: boolean; canCancel: boolean; canAccept?: boolean; onCancel: () => void; onChanged?: () => void;
}) {
  const reviewing = progress?.waiting_for === "anonymization_review";
  const now = useNow(progress?.status === "RUNNING" || progress?.status === "QUEUED");
  const stale = isJobStale(progress, now);
  const views: StageView[] = progress?.stages.map((stage) => ({
    stage_id: stage.stage_id, state: stage.state, error: stage.error, fraction: null,
    seconds: stage.stage_id === "ST-METRIC-CANONICALIZE" ? null : stageSeconds(stage.started_at, stage.completed_at, stage.state === "running" ? now : null),
  })) ?? [];
  return <div className="mx-auto max-w-5xl space-y-4 px-4 py-6 sm:px-6">
    <div><h2 className="text-xl font-bold tracking-tight">Tiến trình xử lý</h2><p className="mt-1 text-sm text-ink-muted">Chọn giai đoạn đã hoàn tất để mở view kết quả.</p></div>
    <Card className="p-5 sm:p-6">
      {reviewing && <AnonymizationReviewPanel key={jobId + ":" + progress.attempt} jobId={jobId} canAccept={canAccept} onAccepted={() => onChanged?.()} />}
      {!reviewing && (progress?.status === "QUEUED" || progress?.waiting_for === "resources" || progress?.queue) && <div role="status" className="mb-5 space-y-2 text-sm text-ink-muted">
        <p>{progress.waiting_for === "resources" ? "Đang chờ đủ tài nguyên trên máy xử lý." : "Job đã vào hàng đợi, đang chờ máy xử lý."} Cấu hình đã chọn được giữ nguyên; job tự chạy tiếp khi đến lượt và đủ tài nguyên.</p>
        <ProgressBar value={null} label="Đang chờ trong hàng đợi" />
        {progress.queue && <QueueStatus queue={progress.queue} />}
        {progress.waiting_for === "resources" && progress.resource_wait && <ResourceWaitDetail wait={progress.resource_wait} />}
      </div>}
      {progress ? (
        <>
          <PipelineTimeline stages={views} stageList={stagesFor(progress.stages.map((stage) => stage.stage_id))} jobId={jobId} isStale={stale} timeNote={"Cập nhật lúc " + new Date(progress.updated_at).toLocaleTimeString("vi-VN") + (stale ? " · Tiến trình mất kết nối" : progress.status === "RUNNING" || progress.status === "QUEUED" ? " · Có thể đóng trang, job tiếp tục chạy trên máy chủ" : "")} />
        </>
      ) : <p role="status" className="text-sm text-ink-muted">Đang tải tiến trình…</p>}
      {canCancel && <div className="mt-4 flex justify-end gap-3">
        <Button variant="danger" size="sm" disabled={busy} onClick={onCancel}><Square aria-hidden />Huỷ xử lý</Button>
      </div>}
    </Card>
    {progress && <AttemptHistory jobId={jobId} attempt={progress.attempt} status={progress.status} />}
    <HelpDetails title="Đầu vào và cách theo dõi">
      {info?.videoName && <p>Video gốc: {info.videoName}{info.videoSize !== null ? " · " + formatBytes(info.videoSize) : ""}</p>}
      {info?.createdBy && <p>Scene do {info.createdBy} tạo.</p>}
      <p>Job vẫn chạy khi bạn rời trang. Bước tỉ lệ mét cần thao tác của bạn trong Studio; view giai đoạn 6 chỉ mở sau khi bước này hoàn tất.</p>
      <p>Thời gian từng bước lấy từ API; thời gian chờ bạn xác nhận không được trình bày như thời gian máy xử lý.</p>
    </HelpDetails>
  </div>;
}
