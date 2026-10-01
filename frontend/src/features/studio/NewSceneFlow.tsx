"use client";

import { ArrowLeft, ArrowRight, Box, Clapperboard, Film, Loader2, LogIn } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button, EmptyState, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { FlowStepper } from "@/features/studio/FlowStepper";
import { canCreateScene, describeDetection } from "@/features/studio/inputKinds";
import { ImportSetupStep } from "@/features/studio/ImportSetupStep";
import { SamplePicker, SampleProcessStep, SampleReadyStep, SampleSelectStep } from "@/features/studio/SampleFlow";
import { UploadDropzone } from "@/features/studio/UploadDropzone";
import { VideoSetupStep } from "@/features/studio/VideoSetupStep";
import { canEdit } from "@/lib/api/auth";
import { getSample, listSamples } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { DemoManifest, SampleSummary, UploadRecord } from "@/lib/contracts/studio";

type Source = "video" | "gaussian" | "sample";
const VIDEO_STEPS = [{ key: "video", label: "Chọn video" }, { key: "settings", label: "Khai báo & tạo job" }];
const IMPORT_STEPS = [{ key: "gaussian", label: "Chọn file 3DGS" }, { key: "import", label: "Mở scene import" }];
const SAMPLE_STEPS = [
  { key: "sample", label: "Chọn mẫu" },
  { key: "inspect", label: "Xem mẫu" },
  { key: "replay", label: "Phát lại có sẵn" },
  { key: "open", label: "Mở scene mẫu" },
];

/**
 * Ba cửa vào dùng chung nguồn upload thật: video tạo job, 3DGS tạo import,
 * mẫu chỉ phát lại artifact đã có. Mỗi nhánh có setup và từ vựng riêng.
 */
export function NewSceneFlow() {
  const searchParams = useSearchParams();
  const { me } = useAuth();
  const [step, setStep] = useState(0);
  const [source, setSource] = useState<Source | null>(null);
  const [preselect, setPreselect] = useState<string | null>(null);
  const [detectedMessage, setDetectedMessage] = useState<string | null>(null);
  const [samples, setSamples] = useState<SampleSummary[]>([]);
  const [samplesReady, setSamplesReady] = useState(false);
  const [samplesError, setSamplesError] = useState<string | null>(null);
  const [sampleId, setSampleId] = useState<string | null>(null);
  const [sample, setSample] = useState<DemoManifest | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void listSamples().then((result) => {
      if (!alive) return;
      setSamplesReady(true);
      if (result.ok) setSamples(result.data.samples);
      else setSamplesError(result.error.detail);
    });
    return () => {
      alive = false;
    };
  }, []);

  // Chỉ nhận kết quả của lần chọn mới nhất: chọn nhanh hai mẫu thì response đến
  // muộn của mẫu trước không được ghi đè mẫu đang hiển thị.
  const latestPick = useRef<string | null>(null);
  const pickSample = useCallback((id: string) => {
    latestPick.current = id;
    setSource("sample");
    setSampleId(id);
    setSample(null);
    setSampleError(null);
    setStep(1);
    void getSample(id).then((result) => {
      if (latestPick.current !== id) return;
      if (result.ok) setSample(result.data);
      else setSampleError(result.error.detail);
    });
  }, []);

  // `/new?sample=<id>` (từ trang Scenes) chọn sẵn video mẫu.
  const requested = searchParams.get("sample");
  useEffect(() => {
    if (!requested) return;
    const timer = setTimeout(() => pickSample(requested), 0);
    return () => clearTimeout(timer);
  }, [requested, pickSample]);

  const backToSample = () => {
    latestPick.current = null;
    setSampleId(null);
    setSample(null);
    setStep(0);
  };

  const chooseSource = (value: Source) => {
    setSource(value);
    setStep(0);
    setPreselect(null);
    setDetectedMessage(null);
  };

  const backToSources = () => {
    latestPick.current = null;
    setSource(null);
    setStep(0);
    setPreselect(null);
    setSampleId(null);
    setSample(null);
    setDetectedMessage(null);
  };

  const uploaded = (record: UploadRecord) => {
    // Máy chủ nhận diện theo nội dung, kể cả khi người dùng chọn sai nhánh từ đuôi file.
    const detected: Source = canCreateScene(record) ? "video" : "gaussian";
    setDetectedMessage(detected === source ? null : `Máy chủ nhận diện file là ${describeDetection(record)}; đã chuyển sang luồng ${detected === "video" ? "dựng từ video" : "mở 3DGS"}.`);
    setSource(detected);
    setPreselect(record.upload_id);
    setStep(1);
  };

  const steps = source === "sample" ? SAMPLE_STEPS : source === "gaussian" ? IMPORT_STEPS : VIDEO_STEPS;

  return (
    <main className={cn("mx-auto px-4 pt-10 pb-20 sm:px-6", sampleId && step >= 2 ? "max-w-6xl" : "max-w-4xl")}>
      <h1 className="text-3xl font-semibold tracking-tight">Scene mới</h1>
      <p className="mt-2 text-[15px] text-ink-muted">
        Chọn cách bắt đầu. Video tạo job dựng scene; file 3DGS mở để xem/chỉnh; mẫu phát lại kết quả đã xử lý sẵn.
      </p>
      {source ? (
        <div className="mt-8 space-y-4">
          <button type="button" onClick={backToSources} className="text-sm font-medium text-ember-strong hover:underline">
            ← Đổi cách bắt đầu
          </button>
          <FlowStepper steps={steps} current={step} />
        </div>
      ) : null}
      <div className="mt-8">
        {!source && (
          <div className="grid gap-4 md:grid-cols-3">
            <SourceCard icon={<Film aria-hidden />} title="Dựng từ video" detail="MP4/MOV → job tái dựng → scene hệ mét" onClick={() => chooseSource("video")} />
            <SourceCard icon={<Box aria-hidden />} title="Mở 3DGS" detail="PLY/ZIP → xem, chỉnh Gaussian và xuất file" onClick={() => chooseSource("gaussian")} />
            <SourceCard icon={<Clapperboard aria-hidden />} title="Thử mẫu" detail="Xem kết quả đã xử lý sẵn, không chạy job mới" onClick={() => chooseSource("sample")} />
          </div>
        )}
        {source && step === 0 && (
          source === "sample" ? (
            !samplesReady ? <p role="status" className="text-sm text-ink-muted">Đang tải video mẫu…</p>
              : samplesError ? <Notice tone="rust">Không tải được video mẫu: {samplesError}</Notice>
                : samples.length === 0 ? <EmptyState icon={<Clapperboard aria-hidden />} title="Chưa có video mẫu">Thử lại khi thư viện mẫu có dữ liệu.</EmptyState>
                  : <SamplePicker samples={samples} selected={sampleId} onPick={pickSample} />
          ) : canEdit(me) ? (
            <div className="space-y-4">
              <UploadDropzone kind={source} onUploaded={uploaded} />
              <div className="flex justify-end">
                <Button variant="ghost" onClick={() => setStep(1)}>
                  Chọn {source === "video" ? "video" : "file 3DGS"} đã tải trước đó
                  <ArrowRight aria-hidden />
                </Button>
              </div>
            </div>
          ) : me !== null ? (
            <EmptyState icon={<LogIn aria-hidden />} title="Đăng nhập để dùng dữ liệu của bạn" action={<Link href="/login?next=/new" className={buttonVariants({})}>Đăng nhập</Link>}>
              Khách có thể thử bằng mẫu đã xử lý sẵn; tải file và tạo job cần tài khoản của nhóm.
            </EmptyState>
          ) : <p role="status" className="text-sm text-ink-muted">Đang kiểm tra quyền truy cập…</p>
        )}
        {detectedMessage && step === 1 && <Notice tone="ochre" className="mb-5">{detectedMessage}</Notice>}
        {source === "sample" && step >= 1 && sampleId ? (
          sampleError ? (
            <div className="space-y-4">
              <Notice tone="rust">Không tải được video mẫu: {sampleError}</Notice>
              <Button variant="ghost" onClick={backToSample}>
                <ArrowLeft aria-hidden />
                Chọn mẫu khác
              </Button>
            </div>
          ) : !sample ? (
            <p className="flex items-center gap-2 text-sm text-ink-muted" role="status">
              <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
              Đang tải video mẫu…
            </p>
          ) : step === 1 ? (
            <SampleSelectStep sampleId={sampleId} sample={sample} onBack={backToSample} onStart={() => setStep(2)} />
          ) : step === 2 ? (
            <SampleProcessStep sampleId={sampleId} sample={sample} onDone={() => setStep(3)} />
          ) : (
            <SampleReadyStep sampleId={sampleId} sample={sample} />
          )
        ) : null}
        {source !== "sample" && source && step === 1 && (
          canEdit(me) ? source === "video"
            ? <VideoSetupStep preselect={preselect} onBack={() => setStep(0)} />
            : <ImportSetupStep preselect={preselect} onBack={() => setStep(0)} />
            : <EmptyState icon={<LogIn aria-hidden />} title="Đăng nhập để tiếp tục" action={<Link href="/login?next=/new" className={buttonVariants({})}>Đăng nhập</Link>}>Phiên đăng nhập đã kết thúc. File đã tải vẫn được lưu trên máy chủ.</EmptyState>
        )}
      </div>
    </main>
  );
}

function SourceCard({ icon, title, detail, onClick }: { icon: React.ReactNode; title: string; detail: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="group flex min-h-48 flex-col items-start rounded-2xl border border-line bg-paper-raised p-5 text-left transition-[border-color,box-shadow] hover:border-ember hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember">
      <span className="grid size-10 place-items-center rounded-xl bg-ember-soft text-ember-strong [&_svg]:size-5">{icon}</span>
      <span className="mt-5 text-lg font-semibold text-ink">{title}</span>
      <span className="mt-1 text-sm leading-relaxed text-ink-muted">{detail}</span>
      <span className="mt-auto flex items-center gap-1 pt-5 text-sm font-medium text-ember-strong">Tiếp tục <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden /></span>
    </button>
  );
}
