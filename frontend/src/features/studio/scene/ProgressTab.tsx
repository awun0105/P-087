"use client";

import { Square } from "lucide-react";
import { Button, Card } from "@/components/studio/primitives";
import { HelpDetails } from "@/components/studio/feedback";
import { PipelineTimeline, type StageView } from "@/features/studio/PipelineTimeline";
import { stageSeconds, useNow, type SceneInfo } from "@/features/studio/scene/state";
import { STUDIO_STAGES } from "@/features/studio/stages";
import { AttemptHistory } from "@/features/studio/scene/AttemptHistory";
import type { JobProgress } from "@/lib/contracts/studio";
import { formatBytes } from "@/lib/format";

/** Tiến trình chỉ quản lý trạng thái; viewer mở qua route giai đoạn riêng. */
export function ProgressTab({ jobId, progress, info, busy, onCancel }: {
  jobId: string; progress: JobProgress | null; info: SceneInfo | null; busy: boolean; onCancel: () => void;
}) {
  const now = useNow(progress?.status === "RUNNING" || progress?.status === "QUEUED");
  const views: StageView[] = progress?.stages.map((stage) => ({
    stage_id: stage.stage_id, state: stage.state, error: stage.error, fraction: null,
    seconds: stage.stage_id === "ST-METRIC-CANONICALIZE" ? null : stageSeconds(stage.started_at, stage.completed_at, stage.state === "running" ? now : null),
  })) ?? [];
  return <div className="mx-auto max-w-5xl space-y-4 px-4 py-6 sm:px-6">
    <div><h2 className="text-xl font-semibold">Tiến trình xử lý</h2><p className="mt-1 text-sm text-ink-muted">Chọn giai đoạn đã hoàn tất để mở view kết quả.</p></div>
    <Card className="p-5 sm:p-6">
      {progress ? <PipelineTimeline stages={views} stageList={STUDIO_STAGES} jobId={jobId} timeNote={"Cập nhật lúc " + new Date(progress.updated_at).toLocaleTimeString("vi-VN")} /> : <p role="status" className="text-sm text-ink-muted">Đang tải tiến trình…</p>}
      {(progress?.status === "RUNNING" || progress?.status === "QUEUED") && !progress.waiting_for && <div className="mt-4 flex justify-end"><Button variant="danger" size="sm" disabled={busy} onClick={onCancel}><Square aria-hidden />Huỷ xử lý</Button></div>}
    </Card>
    {progress && <AttemptHistory jobId={jobId} attempt={progress.attempt} status={progress.status} />}
    <HelpDetails title="Đầu vào và cách theo dõi">
      {info?.videoName && <p>Video gốc: {info.videoName}{info.videoSize !== null ? " · " + formatBytes(info.videoSize) : ""}</p>}
      <p>Job vẫn chạy khi bạn rời trang. Bước tỉ lệ mét cần thao tác của bạn trong Studio; view giai đoạn 6 chỉ mở sau khi bước này hoàn tất.</p>
      <p>Thời gian từng bước lấy từ API; thời gian chờ bạn xác nhận không được trình bày như thời gian máy xử lý.</p>
    </HelpDetails>
  </div>;
}
