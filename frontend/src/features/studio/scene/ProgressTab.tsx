"use client";

import { Check, Clock, Loader2, RotateCcw, Ruler, Square } from "lucide-react";
import { useState } from "react";

import { Button, Card, Notice, formatBytes } from "@/components/studio/primitives";
import { ModeComparisonView } from "@/features/studio/ModeComparisonView";
import { PipelineTimeline, type StageView } from "@/features/studio/PipelineTimeline";
import { ModeButton } from "@/features/studio/scene/badges";
import { stageSeconds, useNow, type SceneInfo } from "@/features/studio/scene/state";
import { STUDIO_STAGES } from "@/features/studio/stages";
import { StageViewer } from "@/features/studio/StageViewer";
import type { JobProgress } from "@/lib/contracts/studio";

export function ProgressTab({
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
