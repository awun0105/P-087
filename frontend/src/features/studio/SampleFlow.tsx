"use client";

import { ArrowLeft, ArrowRight, CheckCircle2, Clapperboard, Clock, FastForward, Info, Play, X } from "lucide-react";
import { useState } from "react";

import { Badge, Button, Card, Notice } from "@/components/studio/primitives";
import { DemoShowcase } from "@/features/studio/DemoShowcase";
import { PipelineTimeline } from "@/features/studio/PipelineTimeline";
import { ProcessingSettings } from "@/features/studio/ProcessingSettings";
import { ProgressFrame } from "@/features/studio/scene/ProgressFrame";
import { stagesFor } from "@/features/studio/stages";
import { useDemoReplay } from "@/features/studio/useDemoReplay";
import { useProcessingForm } from "@/features/studio/useProcessingForm";
import { sampleFileUrl } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { StageId } from "@/lib/contracts/api";
import type { DemoManifest, SampleSummary } from "@/lib/contracts/studio";
import { formatBytes, formatDuration } from "@/lib/format";

/**
 * Luồng video mẫu trong trang Scene mới: cùng các bước như video tải lên, nhưng
 * dùng artifact thật đã xử lý sẵn (demo bundle) nên tiến trình phát lại nhanh.
 */

/** Lưới video mẫu cạnh ô tải video lên. */
export function SamplePicker({
  samples,
  selected,
  onPick,
  onRemove,
  removing = false,
}: {
  samples: SampleSummary[];
  selected?: string | null;
  onPick: (sampleId: string) => void;
  onRemove?: (sample: SampleSummary) => void;
  removing?: boolean;
}) {
  if (samples.length === 0) return null;
  return (
    <section aria-labelledby="samples-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="samples-heading" className="flex items-center gap-2 text-base font-bold">
          <Clapperboard className="size-4 text-ember-strong" aria-hidden />
          Chọn video mẫu
        </h2>
        <p className="text-sm text-ink-muted">Kết quả đã được pipeline xử lý sẵn — tiến trình phát lại nhanh.</p>
      </div>
      <ul className="mt-4 grid gap-4 sm:grid-cols-2">
        {samples.map((sample) => {
          const active = sample.sample_id === selected;
          return (
            <li key={sample.sample_id}>
              <button
                type="button"
                onClick={() => onPick(sample.sample_id)}
                aria-pressed={active}
                className={cn(
                  "group flex w-full cursor-pointer flex-col overflow-hidden rounded-2xl border bg-paper-raised text-left transition-[border-color,box-shadow] duration-200",
                  "focus-visible:ring-3 focus-visible:ring-ember/40 focus-visible:outline-none",
                  active ? "border-ember shadow-md" : "border-line hover:border-line-strong hover:shadow-md",
                )}
              >
                <div className="relative aspect-video bg-viewport">
                  {sample.cover && (
                    // eslint-disable-next-line @next/next/no-img-element -- ảnh mẫu từ API
                    <img src={sampleFileUrl(sample.sample_id, sample.cover)} alt="" className="size-full object-cover" loading="lazy" />
                  )}
                  <Badge tone="ember" className="absolute top-3 left-3 bg-paper-raised/95">
                    Xử lý sẵn
                  </Badge>
                </div>
                <div className="flex flex-1 flex-col p-4">
                  <p className="label-tech text-ink-muted">
                    {sample.source.dataset} · {sample.source.sequence}
                  </p>
                  <p className="mt-1 font-semibold text-ink">{sample.title}</p>
                  {sample.description && <p className="mt-1 line-clamp-2 text-sm text-ink-muted">{sample.description}</p>}
                  <p className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-subtle">
                    {sample.video && <span>{formatBytes(sample.video.size_bytes)}</span>}
                    {sample.frame_count !== null && <span>{sample.frame_count} khung hình</span>}
                    {sample.total_seconds !== null && (
                      <span className="flex items-center gap-1">
                        <Clock className="size-3" aria-hidden />
                        {formatDuration(sample.total_seconds)} xử lý thật
                      </span>
                    )}
                  </p>
                </div>
              </button>
              {onRemove && (
                <Button variant="ghost" size="sm" className="mt-2" disabled={removing}
                  aria-label={`Bỏ ${sample.title} khỏi demo`} onClick={() => onRemove(sample)}>
                  <X aria-hidden />Bỏ khỏi demo
                </Button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Bước "Chọn video" của video mẫu: video, xác nhận dữ liệu và thông số đã dùng (chỉ đọc). */
export function SampleSelectStep({
  sampleId,
  sample,
  onBack,
  onStart,
}: {
  sampleId: string;
  sample: DemoManifest;
  onBack: () => void;
  onStart: () => void;
}) {
  const fileUrl = (name: string) => sampleFileUrl(sampleId, name);
  return (
    <div className="space-y-6">
      <Card className="p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-bold">{sample.title}</h2>
          <Badge tone="ember">Video mẫu · xử lý sẵn</Badge>
          {sample.origin === "smoke_run" && <Badge tone="ochre">Bản smoke tạm</Badge>}
        </div>
        <p className="mt-1 text-sm text-ink-muted">
          {sample.source.dataset} · {sample.source.sequence}. {sample.description}
        </p>
        <div className="mt-4 aspect-video overflow-hidden rounded-xl bg-viewport">
          {sample.video ? (
            <video src={fileUrl(sample.video.name)} className="size-full object-cover" controls muted playsInline preload="metadata" />
          ) : (
            <div className="grid size-full place-items-center text-sm text-on-dark/70">Bundle này không kèm video gốc</div>
          )}
        </div>
        {sample.source.note && (
          <Notice tone="ochre" icon={<Info aria-hidden />} className="mt-4">
            {sample.source.note}
          </Notice>
        )}
        <div className="mt-4 space-y-2 rounded-xl bg-paper-sunken p-4 text-sm text-ink-muted">
          <p className="font-medium text-ink">Xác nhận dữ liệu</p>
          <p className="flex gap-2">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-sage" aria-hidden />
            Có quyền sử dụng video ({sample.source.dataset} công khai).
          </p>
          <p className="flex gap-2">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-sage" aria-hidden />
            Video không có khuôn mặt hoặc biển số chưa làm mờ.
          </p>
        </div>
      </Card>

      <SampleProcessing sample={sample} />

      <div className="flex items-center justify-between gap-3">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft aria-hidden />
          Chọn video khác
        </Button>
        <Button size="lg" onClick={onStart}>
          <Play aria-hidden />
          Xem quá trình đã ghi
        </Button>
      </div>
    </div>
  );
}

/**
 * Thông số thật đã dùng khi xử lý sẵn, hiển thị chỉ đọc. Nhãn/giới hạn lấy từ file
 * cấu hình chung; bundle cũ chưa ghi thông số thì nói rõ thay vì điền giá trị giả.
 */
function SampleProcessing({ sample }: { sample: DemoManifest }) {
  const form = useProcessingForm(Boolean(sample.processing));
  if (!sample.processing) {
    return (
      <Notice tone="neutral" icon={<Info aria-hidden />}>
        Video mẫu này được xử lý trước khi có bảng thông số nên không ghi lại thông số xử lý.
      </Notice>
    );
  }
  if (!form.options) {
    return form.error ? <Notice tone="ochre">Không tải được nhãn thông số: {form.error}</Notice> : null;
  }
  const machine = sample.machine ?? {};
  const machineLabel = [machine.gpu_model, machine.vram, machine.brush].filter(Boolean).join(" · ") || null;
  return <ProcessingSettings parameters={form.options.parameters} values={sample.processing} editable={false} machineLabel={machineLabel} />;
}

/**
 * Bước "Xem tiến trình" của video mẫu: phát lại tiến trình đã ghi theo tỉ lệ thời lượng thật.
 *
 * Cùng khung `ProgressFrame` và cùng danh sách bước (`stagesFor`, có bước LiDAR nếu bundle có) với tab Tiến trình của
 * scene thật; khác ở chỗ bên trái có khung xem trước kết quả của bước, vì mẫu không phải job nên không có trang giai
 * đoạn riêng để mở.
 */
export function SampleProcessStep({
  sampleId,
  sample,
  onDone,
}: {
  sampleId: string;
  sample: DemoManifest;
  onDone: () => void;
}) {
  const stageList = stagesFor(sample.stages.map((stage) => stage.stage_id));
  const { views, finished, skip } = useDemoReplay(sample.stages, true, stageList);
  const [manualStage, setManualStage] = useState<StageId | null>(null);
  const running = views.find((view) => view.state === "running");
  const activeStage = manualStage ?? running?.stage_id ?? views.findLast((view) => view.state === "succeeded")?.stage_id ?? views[0].stage_id;
  const currentView = views.find((view) => view.stage_id === activeStage) ?? views[0];
  const recorded = sample.stages.filter((stage) => (stage.state ?? "succeeded") === "succeeded");
  const missing = stageList.filter((meta) => !recorded.some((stage) => stage.stage_id === meta.id));
  const totalReal = recorded.length > 0 && recorded.every((stage) => stage.duration_seconds !== null)
    ? recorded.reduce((sum, stage) => sum + (stage.duration_seconds ?? 0), 0)
    : null;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
      <div className="space-y-4">
        <DemoShowcase
          demo={sample}
          stage={activeStage}
          fraction={currentView.fraction ?? 1}
          fileUrl={(name) => sampleFileUrl(sampleId, name)}
        />
        {finished ? (
          <Notice tone="ember" icon={<CheckCircle2 aria-hidden />}>
            Scene 3D đã sẵn sàng.{" "}
            <button type="button" onClick={onDone} className="cursor-pointer font-semibold text-ember-strong underline-offset-4 hover:underline">
              Tiếp tục mở scene
            </button>
          </Notice>
        ) : (
          <Notice icon={<Info aria-hidden />}>
            Đây là bản phát lại, không phải job đang chạy: kết quả đã xử lý sẵn, đang phát lại {recorded.length} bước đã ghi trong pipeline {stageList.length} bước.
          </Notice>
        )}
        {missing.length > 0 && <Notice tone="ochre">Mẫu cũ chưa ghi kết quả: {missing.map((meta) => meta.title).join(", ")}.
          Các bước này vẫn hiện chưa có kết quả khi bỏ qua replay.</Notice>}
      </div>
      <ProgressFrame hint="Bấm tên một bước để xem kết quả của bước đó ở khung bên trái.">
        <PipelineTimeline
          stages={views}
          stageList={stageList}
          selectedStage={activeStage}
          onSelectStage={(id) => setManualStage(id)}
          timeNote={totalReal ? `Các bước đã ghi: ${formatDuration(totalReal)}` : "Phát lại nhanh"}
        />
        <div className="mt-6 flex justify-end gap-2">
          {!finished ? (
            <Button variant="ghost" size="sm" onClick={skip}>
              <FastForward aria-hidden />
              Bỏ qua
            </Button>
          ) : (
            <Button onClick={onDone}>
              Mở scene 3D
              <ArrowRight aria-hidden />
            </Button>
          )}
        </div>
      </ProgressFrame>
    </div>
  );
}
