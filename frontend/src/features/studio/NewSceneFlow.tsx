"use client";

import { errorMessage } from "@/lib/ui-error";
import { GAUSSIAN_EDIT_ENABLED } from "@/features/studio/scene/state";

import { ArrowLeft, ArrowRight, Box, Clapperboard, Film, Loader2, LogIn } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button, EmptyState, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { FlowStepper } from "@/features/studio/FlowStepper";
import { canCreateScene, describeDetection, isLidar } from "@/features/studio/inputKinds";
import { ImportSetupStep } from "@/features/studio/ImportSetupStep";
import { SamplePicker, SampleProcessStep, SampleReadyStep, SampleSelectStep } from "@/features/studio/SampleFlow";
import { UploadDropzone } from "@/features/studio/UploadDropzone";
import { VideoSetupStep } from "@/features/studio/VideoSetupStep";
import { canEdit } from "@/lib/api/auth";
import { getSample, listSamples } from "@/lib/api/studio";
import { useUrlState } from "@/features/studio/useUrlState";
import { PageHeader } from "@/components/studio/feedback";
import { cn } from "@/lib/cn";
import type { DemoManifest, SampleSummary, UploadRecord } from "@/lib/contracts/studio";

export type Source = "video" | "gaussian" | "sample";
/** Mỗi cách bắt đầu là một trang riêng dưới `/new`; `/new` chỉ là trang chọn. */
export const SOURCE_ROUTES: Record<Source, string> = {
  video: "/new/import-video",
  gaussian: "/new/import-scene",
  sample: "/new/try-demo",
};
const SOURCE_TITLES: Record<Source, { title: string; description: string }> = {
  video: { title: "Dựng từ video", description: "Tải video MP4/MOV, khai báo dữ liệu rồi bắt đầu dựng scene 3D." },
  gaussian: { title: "Mở 3DGS có sẵn", description: (GAUSSIAN_EDIT_ENABLED ? "Tải file PLY/SOG/ZIP đã dựng để xem, chỉnh Gaussian và xuất file." : "Tải file PLY/SOG/ZIP đã dựng để xem.") + " Không có tỉ lệ mét, collision hay duyệt." },
  sample: { title: "Thử mẫu", description: "Xem tiến trình và kết quả đã xử lý sẵn; không tạo scene mới." },
};
const VIDEO_STEPS = [{ key: "video", label: "Chọn video" }, { key: "settings", label: "Khai báo & tạo job" }];
const IMPORT_STEPS = [{ key: "gaussian", label: "Chọn file 3DGS" }, { key: "import", label: "Mở scene import" }];
const SAMPLE_STEPS = [
  { key: "sample", label: "Chọn mẫu" },
  { key: "inspect", label: "Xem mẫu" },
  { key: "replay", label: "Tiến trình đã ghi" },
  { key: "open", label: "Mở scene mẫu" },
];

/**
 * Ba cửa vào dùng chung nguồn upload thật: video tạo job, 3DGS tạo import, mẫu chỉ phát lại artifact đã có. Mỗi nhánh
 * là một trang (`SOURCE_ROUTES`) có setup và từ vựng riêng; `source` do trang truyền vào, không đọc từ query.
 * `source = null` là trang chọn `/new`; link cũ dạng `/new?source=…` hoặc `/new?sample=…` được chuyển sang trang mới.
 */
export function NewSceneFlow({ source = null }: { source?: Source | null }) {
  const { me } = useAuth();
  return <NewSceneFlowBody source={source} key={me?.user?.user_id ?? (me?.auth_required ? "guest" : "local")} />;
}
function NewSceneFlowBody({ source }: { source: Source | null }) {
  const { params, update } = useUrlState();
  const { me } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [preselect, setPreselect] = useState<string | null>(null);
  const [lidarNotice, setLidarNotice] = useState<string | null>(null);
  const routeKey = params.toString();
  useEffect(() => {
    const timer = setTimeout(() => {
      const route = new URLSearchParams(routeKey);
      if (source === null) {
        const legacy = route.get("source");
        const target = legacy === "video" || legacy === "gaussian" || legacy === "sample" ? legacy : route.get("sample") ? "sample" : null;
        if (target) {
          route.delete("source");
          router.replace(SOURCE_ROUTES[target] + (route.size ? "?" + route.toString() : ""));
        }
      } else if (source === "sample") {
        setStep(route.get("sample") ? route.get("step") === "replay" ? 2 : route.get("step") === "ready" ? 3 : 1 : 0);
      } else {
        setStep(route.get("step") === "setup" ? 1 : 0);
        setPreselect(route.get("upload"));
      }
    }, 0);
    return () => clearTimeout(timer);
  }, [routeKey, source, router]);
  // Máy chủ nhận diện theo nội dung; file thuộc nhánh khác thì `uploaded` chuyển trang kèm `switched=1`.
  const detectedMessage = source && source !== "sample" && params.get("switched")
    ? `Máy chủ nhận diện file theo nội dung, không theo đuôi file; đã chuyển sang luồng ${source === "video" ? "dựng từ video" : "mở 3DGS"}.`
    : null;
  const [samples, setSamples] = useState<SampleSummary[]>([]);
  const [samplesReady, setSamplesReady] = useState(false);
  const [samplesError, setSamplesError] = useState<string | null>(null);
  const [samplesReload, setSamplesReload] = useState(0);
  const [sampleId, setSampleId] = useState<string | null>(null);
  const [sample, setSample] = useState<DemoManifest | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void listSamples().then((result) => {
      if (!alive) return;
      setSamplesReady(true);
      if (result.ok) setSamples(result.data.samples);
      else setSamplesError(errorMessage(result.error));
    });
    return () => {
      alive = false;
    };
  }, [samplesReload]);

  // Chỉ nhận kết quả của lần chọn mới nhất: chọn nhanh hai mẫu thì response đến
  // muộn của mẫu trước không được ghi đè mẫu đang hiển thị.
  const latestPick = useRef<string | null>(null);
  const pickSample = useCallback((id: string) => {
    latestPick.current = id;
    if (window.location.search.indexOf("sample=" + encodeURIComponent(id)) === -1) update({ sample: id, step: "setup", upload: null });
    setSampleId(id);
    setSample(null);
    setSampleError(null);
    const routeStep = new URLSearchParams(window.location.search).get("step");
    setStep(routeStep === "replay" ? 2 : routeStep === "ready" ? 3 : 1);
    void getSample(id).then((result) => {
      if (latestPick.current !== id) return;
      if (result.ok) setSample(result.data);
      else setSampleError(errorMessage(result.error));
    });
  }, [update]);

  // `/new/try-demo?sample=<id>` chọn sẵn video mẫu.
  const requested = source === "sample" ? params.get("sample") : null;
  useEffect(() => {
    if (!requested) return;
    const timer = setTimeout(() => pickSample(requested), 0);
    return () => clearTimeout(timer);
  }, [requested, pickSample]);

  const backToSample = () => {
    update({ sample: null, step: "input" });
    latestPick.current = null;
    setSampleId(null);
    setSample(null);
    setStep(0);
  };

  const uploaded = (record: UploadRecord) => {
    // Máy chủ nhận diện theo nội dung, kể cả khi người dùng chọn sai nhánh từ đuôi file.
    if (isLidar(record)) {
      // LiDAR không phải video hay scene 3DGS (ADR 0009): nói rõ đã nhận diện gì, không đẩy sang nhánh import 3DGS.
      setLidarNotice(`Máy chủ nhận diện file là ${describeDetection(record)}. Đây là dữ liệu LiDAR, không phải ${source === "video" ? "video" : "scene 3DGS"}; file đã được lưu nhưng trang này không dùng nó.`);
      return;
    }
    setLidarNotice(null);
    const detected: Source = canCreateScene(record) ? "video" : "gaussian";
    if (detected !== source) {
      router.push(`${SOURCE_ROUTES[detected]}?step=setup&upload=${encodeURIComponent(record.upload_id)}&switched=1`);
      return;
    }
    update({ step: "setup", upload: record.upload_id, sample: null, switched: null });
    setPreselect(record.upload_id);
    setStep(1);
  };

  const steps = source === "sample" ? SAMPLE_STEPS : source === "gaussian" ? IMPORT_STEPS : VIDEO_STEPS;
  const loginHref = "/login?next=" + encodeURIComponent((source ? SOURCE_ROUTES[source] : "/new") + (routeKey ? "?" + routeKey : ""));
  const heading = source ? SOURCE_TITLES[source] : { title: "Tạo scene mới", description: "Chọn nguồn dữ liệu cho scene." };

  return (
    <main className={cn("mx-auto px-4 pt-10 pb-20 sm:px-6", sampleId && step >= 2 ? "max-w-6xl" : "max-w-4xl")}>
      <PageHeader title={heading.title} description={heading.description} />
      {source ? (
        <div className="mt-8 space-y-4">
          {canEdit(me) ? (
            <Link href="/new" className="text-sm font-medium text-ember-strong hover:underline">
              ← Đổi cách bắt đầu
            </Link>
          ) : (
            <Link href="/login" className="text-sm font-medium text-ember-strong hover:underline">
              ← Quay lại đăng nhập
            </Link>
          )}
          <FlowStepper steps={steps} current={step} />
        </div>
      ) : null}
      <div className="mt-8">
        {!source && (
          <div className="space-y-4">
            <SourceCard primary icon={<Film aria-hidden />} title={SOURCE_TITLES.video.title} detail={SOURCE_TITLES.video.description} href={SOURCE_ROUTES.video} />
            <p className="label-tech pt-2 text-ink-muted">Không dựng mới</p>
            <div className="grid gap-4 md:grid-cols-2">
              <SourceCard icon={<Box aria-hidden />} title={SOURCE_TITLES.gaussian.title} detail={SOURCE_TITLES.gaussian.description} href={SOURCE_ROUTES.gaussian} />
              <SourceCard icon={<Clapperboard aria-hidden />} title={SOURCE_TITLES.sample.title} detail={SOURCE_TITLES.sample.description} href={SOURCE_ROUTES.sample} />
            </div>
          </div>
        )}
        {source && step === 0 && (
          source === "sample" ? (
            !samplesReady ? <p role="status" className="text-sm text-ink-muted">Đang tải video mẫu…</p>
              : samplesError ? <Notice tone="rust">Không tải được video mẫu: {samplesError} <Button variant="secondary" size="sm" onClick={() => { setSamplesReady(false); setSamplesError(null); setSamplesReload((value) => value + 1); }}>Thử lại</Button></Notice>
                : samples.length === 0 ? <EmptyState icon={<Clapperboard aria-hidden />} title="Chưa có video mẫu">Thử lại khi thư viện mẫu có dữ liệu.</EmptyState>
                  : <SamplePicker samples={samples} selected={sampleId} onPick={pickSample} />
          ) : canEdit(me) ? (
            <div className="space-y-4">
              <UploadDropzone kind={source} onUploaded={uploaded} />
              {lidarNotice && <Notice tone="ochre">{lidarNotice}</Notice>}
              <div className="flex justify-end">
                <Button variant="ghost" onClick={() => { setStep(1); update({ step: "setup" }); }}>
                  Chọn {source === "video" ? "video" : "file 3DGS"} đã tải trước đó
                  <ArrowRight aria-hidden />
                </Button>
              </div>
            </div>
          ) : me !== null ? (
            <EmptyState icon={<LogIn aria-hidden />} title="Đăng nhập để dùng dữ liệu của bạn" action={<Link href={loginHref} className={buttonVariants({})}>Đăng nhập</Link>}>
              Khách có thể thử bằng mẫu đã xử lý sẵn; tải file và tạo job cần tài khoản của nhóm.
            </EmptyState>
          ) : <p role="status" className="text-sm text-ink-muted">Đang kiểm tra quyền truy cập…</p>
        )}
        {detectedMessage && step === 1 && <Notice tone="ochre" className="mb-5">{detectedMessage}</Notice>}
        {source === "sample" && step >= 1 && sampleId ? (
          sampleError ? (
            <div className="space-y-4">
              <Notice tone="rust">Không tải được video mẫu: {sampleError} <Button size="sm" variant="secondary" onClick={() => pickSample(sampleId)}>Thử lại</Button></Notice>
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
            <SampleSelectStep sampleId={sampleId} sample={sample} onBack={backToSample} onStart={() => { setStep(2); update({ step: "replay" }); }} />
          ) : step === 2 ? (
            <SampleProcessStep sampleId={sampleId} sample={sample} onDone={() => { setStep(3); update({ step: "ready" }); }} />
          ) : (
            <SampleReadyStep sampleId={sampleId} sample={sample} />
          )
        ) : null}
        {source !== "sample" && source && step === 1 && (
          canEdit(me) ? source === "video"
            ? <VideoSetupStep preselect={preselect} onBack={() => { setStep(0); update({ step: "input" }); }} />
            : <ImportSetupStep preselect={preselect} onBack={() => { setStep(0); update({ step: "input" }); }} />
            : <EmptyState icon={<LogIn aria-hidden />} title="Đăng nhập để tiếp tục" action={<Link href={loginHref} className={buttonVariants({})}>Đăng nhập</Link>}>Phiên đăng nhập đã kết thúc. File đã tải vẫn được lưu trên máy chủ.</EmptyState>
        )}
      </div>
    </main>
  );
}

function SourceCard({ icon, title, detail, href, primary = false }: { icon: React.ReactNode; title: string; detail: string; href: string; primary?: boolean }) {
  return (
    <Link href={href} className={cn("group flex rounded-2xl border bg-paper-raised p-5 text-left transition-[border-color,box-shadow] hover:border-ember hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember", primary ? "items-center gap-5 border-ember/50 sm:p-6" : "min-h-40 flex-col items-start border-line")}>
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-ember-soft text-ember-strong [&_svg]:size-5">{icon}</span>
      <span className={cn("flex min-w-0 flex-1 flex-col", primary ? "" : "mt-4")}>
        <span className="text-lg font-bold tracking-tight text-ink">{title}</span>
        <span className="mt-1 text-sm leading-relaxed text-ink-muted">{detail}</span>
      </span>
      <span className={cn("flex items-center gap-1 text-sm font-medium text-ember-strong", primary ? "" : "mt-auto pt-4")}>Tiếp tục <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden /></span>
    </Link>
  );
}
