"use client";

import { errorMessage } from "@/lib/ui-error";
import { SOURCE_ROUTES, SOURCE_TITLES, type Source } from "@/features/studio/newSceneSources";

import { ArrowLeft, ArrowRight, Clapperboard, Loader2, LogIn } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button, EmptyState, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { FlowStepper } from "@/features/studio/FlowStepper";
import { canCreateScene, describeDetection, isLidar } from "@/features/studio/inputKinds";
import { ImportSetupStep } from "@/features/studio/ImportSetupStep";
import { SamplePicker, SampleProcessStep, SampleSelectStep } from "@/features/studio/SampleFlow";
import { UploadDropzone } from "@/features/studio/UploadDropzone";
import { canEdit } from "@/lib/api/auth";
import { getSample, listSamples } from "@/lib/api/studio";
import { useUrlState } from "@/features/studio/useUrlState";
import { PageHeader } from "@/components/studio/feedback";
import { cn } from "@/lib/cn";
import type { DemoManifest, SampleSummary, UploadRecord } from "@/lib/contracts/studio";

const IMPORT_STEPS = [{ key: "gaussian", label: "Chọn file 3DGS" }, { key: "import", label: "Mở scene import" }];
const SAMPLE_STEPS = [
  { key: "sample", label: "Chọn mẫu" },
  { key: "inspect", label: "Xem thông tin" },
  { key: "replay", label: "Xem tiến trình" },
];

/** Hai cửa vào dùng kết quả đã dựng sẵn: 3DGS tạo import, mẫu chỉ phát lại artifact đã có. */
export type ReadyMadeSource = Exclude<Source, "video">;

/**
 * Hai cửa vào cho dữ liệu đã dựng sẵn. Dựng scene từ đầu đi qua khung tải input chung ở `/new`
 * (`UnifiedInputFlow`), nên trang này không có nhánh video riêng. Mỗi nhánh là một trang
 * (`SOURCE_ROUTES`) có setup và từ vựng riêng; `source` do trang truyền vào, không đọc từ query.
 */
export function NewSceneFlow({ source }: { source: ReadyMadeSource }) {
  const { me } = useAuth();
  return <NewSceneFlowBody source={source} key={me?.user?.user_id ?? (me?.auth_required ? "guest" : "local")} />;
}
function NewSceneFlowBody({ source }: { source: ReadyMadeSource }) {
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
      if (source === "sample") {
        // `step=ready` là URL cũ của bước mở scene đã bỏ: quay về bước xem tiến trình.
        setStep(route.get("sample") ? route.get("step") === "replay" || route.get("step") === "ready" ? 2 : 1 : 0);
      } else {
        setStep(route.get("step") === "setup" ? 1 : 0);
        setPreselect(route.get("upload"));
      }
    }, 0);
    return () => clearTimeout(timer);
  }, [routeKey, source]);
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
    setStep(routeStep === "replay" || routeStep === "ready" ? 2 : 1);
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
    // Máy chủ nhận diện theo nội dung, kể cả khi người dùng vào nhánh này với file khác.
    if (isLidar(record)) {
      // LiDAR không phải video hay scene 3DGS (ADR 0009): nói rõ đã nhận diện gì, không đẩy sang nhánh import 3DGS.
      setLidarNotice(`Máy chủ nhận diện file là ${describeDetection(record)}. Đây là dữ liệu LiDAR, không phải scene 3DGS; file đã được lưu nhưng trang này không dùng nó.`);
      return;
    }
    setLidarNotice(null);
    if (canCreateScene(record)) {
      // Video thuộc khung tải input chung; nối upload đã xác minh sang đó thay vì bắt tải lại.
      router.push(`${SOURCE_ROUTES.video}?upload=${encodeURIComponent(record.upload_id)}`);
      return;
    }
    update({ step: "setup", upload: record.upload_id, sample: null });
    setPreselect(record.upload_id);
    setStep(1);
  };

  const steps = source === "sample" ? SAMPLE_STEPS : IMPORT_STEPS;
  const loginHref = "/login?next=" + encodeURIComponent(SOURCE_ROUTES[source] + (routeKey ? "?" + routeKey : ""));
  const heading = SOURCE_TITLES[source];

  return (
    <main className={cn("mx-auto px-4 pt-10 pb-20 sm:px-6", sampleId && step >= 2 ? "max-w-6xl" : "max-w-4xl")}>
      <PageHeader title={heading.title} description={heading.description} />
      <div className="mt-8 space-y-4">
        {canEdit(me) ? (
          <Link href={SOURCE_ROUTES.video} className="text-sm font-medium text-ember-strong hover:underline">
            ← Về khung tải input
          </Link>
        ) : (
          <Link href="/login" className="text-sm font-medium text-ember-strong hover:underline">
            ← Quay lại đăng nhập
          </Link>
        )}
        <FlowStepper steps={steps} current={step} />
      </div>
      <div className="mt-8">
        {step === 0 && (
          source === "sample" ? (
            !samplesReady ? <p role="status" className="text-sm text-ink-muted">Đang tải video mẫu…</p>
              : samplesError ? <Notice tone="rust">Không tải được video mẫu: {samplesError} <Button variant="secondary" size="sm" onClick={() => { setSamplesReady(false); setSamplesError(null); setSamplesReload((value) => value + 1); }}>Thử lại</Button></Notice>
                : samples.length === 0 ? <EmptyState icon={<Clapperboard aria-hidden />} title="Chưa có video mẫu">Thử lại khi thư viện mẫu có dữ liệu.</EmptyState>
                  : <SamplePicker samples={samples} selected={sampleId} onPick={pickSample} />
          ) : canEdit(me) ? (
            <div className="space-y-4">
              <UploadDropzone onUploaded={uploaded} />
              {lidarNotice && <Notice tone="ochre">{lidarNotice}</Notice>}
              <div className="flex justify-end">
                <Button variant="ghost" onClick={() => { setStep(1); update({ step: "setup" }); }}>
                  Chọn file 3DGS đã tải trước đó
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
          ) : (
            <SampleProcessStep sampleId={sampleId} sample={sample} onDone={() => router.push(`/samples/${encodeURIComponent(sampleId)}/scene`)} />
          )
        ) : null}
        {source === "gaussian" && step === 1 && (
          canEdit(me)
            ? <ImportSetupStep preselect={preselect} onBack={() => { setStep(0); update({ step: "input" }); }} />
            : <EmptyState icon={<LogIn aria-hidden />} title="Đăng nhập để tiếp tục" action={<Link href={loginHref} className={buttonVariants({})}>Đăng nhập</Link>}>Phiên đăng nhập đã kết thúc. File đã tải vẫn được lưu trên máy chủ.</EmptyState>
        )}
      </div>
    </main>
  );
}
