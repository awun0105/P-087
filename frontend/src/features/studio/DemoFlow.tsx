"use client";

import { ArrowRight, Box, CheckCircle2, FastForward, Film, Info, Loader2, Play, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Button, Card, EmptyState, Notice, ProgressBar, buttonVariants, formatBytes, formatDuration } from "@/components/studio/primitives";
import { DemoShowcase } from "@/features/studio/DemoShowcase";
import { FlowStepper } from "@/features/studio/FlowStepper";
import { GuideCallout } from "@/features/studio/GuideCallout";
import { PipelineTimeline } from "@/features/studio/PipelineTimeline";
import { ProcessingSettings } from "@/features/studio/ProcessingSettings";
import { useProcessingForm } from "@/features/studio/useProcessingForm";
import { MVP_STAGES } from "@/features/studio/stages";
import { useDemoReplay } from "@/features/studio/useDemoReplay";
import { demoFileUrl, getDemo } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { DemoManifest } from "@/lib/contracts/studio";

const STEPS = [
  { key: "upload", label: "Tải video lên" },
  { key: "select", label: "Chọn video" },
  { key: "process", label: "Xử lý" },
  { key: "scene", label: "Mở scene" },
] as const;

/** Kịch bản demo có hướng dẫn: cùng các bước như người dùng thật, kết quả đã xử lý sẵn. */
export function DemoFlow() {
  const [demo, setDemo] = useState<DemoManifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(0);

  useEffect(() => {
    let alive = true;
    void getDemo().then((result) => {
      if (!alive) return;
      if (result.ok) setDemo(result.data);
      else setError(result.error.status === 404 ? "missing" : result.error.detail);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (error === "missing") {
    return (
      <Shell>
        <EmptyState icon={<Film aria-hidden />} title="Chưa có kịch bản demo trên máy này">
          Export demo bundle từ một job đã chạy (scripts/demo/export_demo_bundle.py) rồi đặt PRODUCT_DEMO_DIR.
        </EmptyState>
      </Shell>
    );
  }
  if (error || !demo) {
    return (
      <Shell>
        {error ? (
          <Notice tone="rust">Không tải được kịch bản demo: {error}</Notice>
        ) : (
          <div className="flex items-center gap-2 text-sm text-ink-muted" role="status">
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
            Đang tải kịch bản demo…
          </div>
        )}
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">{demo.title}</h1>
        <Badge tone="ember">Kịch bản demo · đã xử lý sẵn</Badge>
        {demo.origin === "smoke_run" && <Badge tone="ochre">Bản smoke tạm</Badge>}
      </div>
      <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-ink-muted">
        {demo.source.dataset} · {demo.source.sequence}. Mỗi bước dưới đây giống hệt khi bạn dùng video của mình; riêng
        kết quả đã được pipeline tính trước nên tiến trình chạy nhanh.
      </p>
      {demo.source.note && (
        <Notice tone="ochre" icon={<Info aria-hidden />} className="mt-4 max-w-2xl">
          {demo.source.note}
        </Notice>
      )}
      <div className="mt-8">
        <FlowStepper steps={STEPS} current={step} />
      </div>
      <div className="mt-8">
        {step === 0 && <UploadStep demo={demo} onDone={() => setStep(1)} />}
        {step === 1 && <SelectStep demo={demo} onStart={() => setStep(2)} />}
        {step === 2 && <ProcessStep demo={demo} onDone={() => setStep(3)} />}
        {step === 3 && <SceneStep demo={demo} />}
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-6">{children}</main>;
}

/** Bước 1: "tải" video demo — thanh tiến độ ghi rõ là mô phỏng vì file đã có sẵn. */
function UploadStep({ demo, onDone }: { demo: DemoManifest; onDone: () => void }) {
  const [progress, setProgress] = useState<number | null>(null);
  useEffect(() => {
    if (progress === null) return;
    if (progress >= 1) {
      const timer = setTimeout(onDone, 350);
      return () => clearTimeout(timer);
    }
    const timer = setTimeout(() => setProgress((value) => Math.min(1, (value ?? 0) + 0.08)), 60);
    return () => clearTimeout(timer);
  }, [progress, onDone]);

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card className="p-5 sm:p-6">
        <div className="aspect-video overflow-hidden rounded-xl bg-viewport">
          {demo.video ? (
            <video src={demoFileUrl(demo.video.name)} className="size-full object-cover" controls muted playsInline preload="metadata" />
          ) : (
            <div className="grid size-full place-items-center text-sm text-paper/70">Bundle này không kèm video gốc</div>
          )}
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{demo.video?.name ?? "Video demo"}</p>
            <p className="text-sm text-ink-muted">
              {demo.video ? formatBytes(demo.video.size_bytes) : "—"} · camera di chuyển trên robot trong kho
            </p>
          </div>
          <Button onClick={() => setProgress(0)} disabled={progress !== null} size="lg">
            <Upload aria-hidden />
            Tải video demo lên
          </Button>
        </div>
        {progress !== null && (
          <div className="mt-5">
            <ProgressBar value={progress} label="Tải video demo" />
            <p className="mt-2 text-xs text-ink-subtle">Mô phỏng tải lên — video demo đã có sẵn trên máy chủ.</p>
          </div>
        )}
      </Card>
      <GuideCallout step={1} total={4} title="Tải video lên">
        Người dùng bắt đầu bằng việc tải video quay kho. Bấm <strong>Tải video demo lên</strong> để dùng video mẫu.
      </GuideCallout>
    </div>
  );
}

/** Bước 2: chọn video đã tải để xử lý, kèm lời khai quyền riêng tư (đã điền cho dữ liệu công khai). */
function SelectStep({ demo, onStart }: { demo: DemoManifest; onStart: () => void }) {
  const [selected, setSelected] = useState(true);
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card className="p-5 sm:p-6">
        <h2 className="text-base font-semibold">Video đã tải lên</h2>
        <fieldset className="mt-4">
          <legend className="sr-only">Chọn video để xử lý</legend>
          <label
            className={cn(
              "flex cursor-pointer items-center gap-4 rounded-xl border p-3 transition-colors duration-200",
              selected ? "border-ember bg-ember-soft/50" : "border-line hover:border-line-strong",
            )}
          >
            <input type="radio" name="demo-video" checked={selected} onChange={() => setSelected(true)} className="size-4 accent-ember-strong" />
            <div className="h-14 w-24 shrink-0 overflow-hidden rounded-lg bg-viewport">
              {demo.frames[0] && (
                // eslint-disable-next-line @next/next/no-img-element -- ảnh demo từ API
                <img src={demoFileUrl(demo.frames[0].name)} alt="" className="size-full object-cover" />
              )}
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{demo.video?.name ?? demo.title}</p>
              <p className="text-sm text-ink-muted">{demo.video ? formatBytes(demo.video.size_bytes) : "Video demo"} · vừa tải lên</p>
            </div>
          </label>
        </fieldset>
        <div className="mt-6 space-y-2 rounded-xl bg-paper-sunken p-4 text-sm text-ink-muted">
          <p className="font-medium text-ink">Xác nhận dữ liệu</p>
          <p className="flex gap-2"><CheckCircle2 className="mt-0.5 size-4 shrink-0 text-sage" aria-hidden />Có quyền sử dụng video ({demo.source.dataset} công khai).</p>
          <p className="flex gap-2"><CheckCircle2 className="mt-0.5 size-4 shrink-0 text-sage" aria-hidden />Video không có khuôn mặt hoặc biển số chưa làm mờ.</p>
        </div>
        <div className="mt-6">
          <DemoProcessing demo={demo} />
        </div>
        <div className="mt-6 flex justify-end">
          <Button size="lg" onClick={onStart} disabled={!selected}>
            <Play aria-hidden />
            Bắt đầu xử lý
          </Button>
        </div>
      </Card>
      <GuideCallout step={2} total={4} title="Chọn video để dựng scene">
        Video vừa tải nằm trong danh sách. Chọn nó, kiểm tra phần xác nhận dữ liệu rồi bấm <strong>Bắt đầu xử lý</strong>.
      </GuideCallout>
    </div>
  );
}

/**
 * Thông số thật đã dùng khi xử lý sẵn, hiển thị chỉ đọc. Nhãn/giới hạn lấy từ file
 * cấu hình chung; bundle cũ chưa ghi thông số thì nói rõ thay vì điền giá trị giả.
 */
function DemoProcessing({ demo }: { demo: DemoManifest }) {
  const form = useProcessingForm(Boolean(demo.processing));
  if (!demo.processing) {
    return (
      <Notice tone="neutral" icon={<Info aria-hidden />}>
        Bundle demo này được tạo trước khi có bảng thông số nên không ghi lại thông số xử lý.
      </Notice>
    );
  }
  if (!form.options) {
    return form.error ? <Notice tone="ochre">Không tải được nhãn thông số: {form.error}</Notice> : null;
  }
  const machine = demo.machine ?? {};
  const machineLabel = [machine.gpu_model, machine.vram, machine.brush].filter(Boolean).join(" · ") || null;
  return (
    <ProcessingSettings
      parameters={form.options.parameters}
      values={demo.processing}
      editable={false}
      machineLabel={machineLabel}
    />
  );
}

/** Bước 3: phát lại tiến trình từng stage theo tỉ lệ thời lượng thật đã ghi. */
function ProcessStep({ demo, onDone }: { demo: DemoManifest; onDone: () => void }) {
  const { views, finished, skip } = useDemoReplay(demo.stages, true);
  const running = views.find((view) => view.state === "running");
  const shown = running ?? views[views.length - 1];
  const totalReal = demo.stages.every((stage) => stage.duration_seconds !== null)
    ? demo.stages.reduce((sum, stage) => sum + (stage.duration_seconds ?? 0), 0)
    : null;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
      <div className="space-y-6">
        <DemoShowcase demo={demo} stage={shown.stage_id} fraction={shown.fraction ?? 1} />
        {finished ? (
          <Notice tone="ember" icon={<CheckCircle2 aria-hidden />}>
            Scene 3D đã sẵn sàng.{" "}
            <button type="button" onClick={onDone} className="cursor-pointer font-semibold text-ember-strong underline-offset-4 hover:underline">
              Tiếp tục mở scene
            </button>
          </Notice>
        ) : (
          <GuideCallout step={3} total={4} title="Theo dõi từng giai đoạn">
            Pipeline chạy lần lượt {MVP_STAGES.length} giai đoạn. Với video thật, bạn có thể rời trang — job vẫn chạy trên máy chủ.
          </GuideCallout>
        )}
      </div>
      <Card className="h-fit p-5 sm:p-6">
        <PipelineTimeline
          stages={views}
          timeNote={totalReal ? `Trên GPU thật: ${formatDuration(totalReal)}` : "Phát lại nhanh"}
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
      </Card>
    </div>
  );
}

/** Bước 4: vào editor 3D với file 3DGS của demo. */
function SceneStep({ demo }: { demo: DemoManifest }) {
  const cover = demo.frames[Math.floor(demo.frames.length / 2)];
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card className="overflow-hidden">
        <div className="relative aspect-[16/8] bg-viewport">
          {cover && (
            // eslint-disable-next-line @next/next/no-img-element -- ảnh demo từ API
            <img src={demoFileUrl(cover.name)} alt="" className="size-full object-cover opacity-80" />
          )}
          <div className="absolute inset-0 grid place-items-center">
            <Link href="/demo/scene" className={buttonVariants({ size: "lg" })}>
              <Box aria-hidden />
              Mở scene 3D
            </Link>
          </div>
        </div>
        <div className="p-5 text-sm text-ink-muted">
          File 3DGS: <span className="font-mono text-xs">{demo.splat.name}</span> · {formatBytes(demo.splat.size_bytes)}
        </div>
      </Card>
      <GuideCallout step={4} total={4} title="Xem và chỉnh sửa scene">
        Trong editor, xoay/zoom để xem, dùng công cụ chọn để xóa hoặc di chuyển vùng Gaussian, đo khoảng cách và xuất
        file PLY/SOG.
      </GuideCallout>
    </div>
  );
}
