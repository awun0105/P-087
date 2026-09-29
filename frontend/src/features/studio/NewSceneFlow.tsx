"use client";

import { ArrowLeft, ArrowRight, Film, Loader2, LogIn, Play } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { Button, Card, EmptyState, Notice, buttonVariants, formatBytes } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { FlowStepper } from "@/features/studio/FlowStepper";
import { canCreateScene, describeDetection } from "@/features/studio/inputKinds";
import { SamplePicker, SampleProcessStep, SampleReadyStep, SampleSelectStep } from "@/features/studio/SampleFlow";
import { ProcessingSettings } from "@/features/studio/ProcessingSettings";
import { useProcessingForm } from "@/features/studio/useProcessingForm";
import { UploadDropzone } from "@/features/studio/UploadDropzone";
import { canEdit } from "@/lib/api/auth";
import { createSceneFromUpload, getSample, listSamples, listUploads } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { DataOrigin, DemoManifest, SampleSummary, UploadRecord } from "@/lib/contracts/studio";

const STEPS = [
  { key: "upload", label: "Tải video lên" },
  { key: "select", label: "Chọn video" },
  { key: "process", label: "Xử lý" },
  { key: "scene", label: "Mở scene" },
] as const;

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" });

const ORIGINS: { value: DataOrigin; label: string }[] = [
  { value: "self_collected_no_pii", label: "Tự quay, không có người/biển số" },
  { value: "anonymized", label: "Đã làm mờ khuôn mặt/biển số" },
  { value: "public_or_synthetic", label: "Dữ liệu công khai hoặc tổng hợp" },
];

/**
 * Luồng tạo scene: tải video của mình (job thật trên máy chủ GPU) hoặc chọn video mẫu
 * đã xử lý sẵn — video mẫu đi qua cùng các bước nhưng phát lại kết quả thật đã lưu.
 */
export function NewSceneFlow() {
  const searchParams = useSearchParams();
  const { me } = useAuth();
  const [step, setStep] = useState(0);
  const [preselect, setPreselect] = useState<string | null>(null);
  const [samples, setSamples] = useState<SampleSummary[]>([]);
  const [sampleId, setSampleId] = useState<string | null>(null);
  const [sample, setSample] = useState<DemoManifest | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void listSamples().then((result) => {
      // Deployment chưa có thư viện mẫu → chỉ ẩn phần video mẫu, không chặn luồng tải lên.
      if (alive && result.ok) setSamples(result.data.samples);
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

  const backToUpload = () => {
    latestPick.current = null;
    setSampleId(null);
    setSample(null);
    setStep(0);
  };

  return (
    <main className={cn("mx-auto px-4 pt-10 pb-20 sm:px-6", sampleId && step >= 2 ? "max-w-6xl" : "max-w-4xl")}>
      <h1 className="text-3xl font-semibold tracking-tight">Scene mới</h1>
      <p className="mt-2 text-[15px] text-ink-muted">
        Tải video quay kho hoặc chọn một video mẫu, hệ thống dựng scene 3D trên máy chủ GPU.
      </p>
      <div className="mt-8">
        <FlowStepper steps={STEPS} current={step} />
      </div>
      <div className="mt-8">
        {step === 0 && (
          <div className="space-y-10">
            {canEdit(me) ? (
              <div className="space-y-4">
                <UploadDropzone
                  onUploaded={(record) => {
                    setPreselect(record.upload_id);
                    setStep(1);
                  }}
                />
                <div className="flex justify-end">
                  <Button variant="ghost" onClick={() => setStep(1)}>
                    Chọn video đã tải trước đó
                    <ArrowRight aria-hidden />
                  </Button>
                </div>
              </div>
            ) : me !== null ? (
              <EmptyState
                icon={<LogIn aria-hidden />}
                title="Đăng nhập để tải video của bạn"
                action={
                  <Link href="/login?next=/new" className={buttonVariants({})}>
                    Đăng nhập
                  </Link>
                }
              >
                Xử lý video dùng máy chủ GPU nên cần tài khoản của nhóm. Bạn vẫn có thể thử ngay với video mẫu bên dưới.
              </EmptyState>
            ) : null}
            <SamplePicker samples={samples} selected={sampleId} onPick={pickSample} />
          </div>
        )}
        {step >= 1 && sampleId ? (
          sampleError ? (
            <div className="space-y-4">
              <Notice tone="rust">Không tải được video mẫu: {sampleError}</Notice>
              <Button variant="ghost" onClick={backToUpload}>
                <ArrowLeft aria-hidden />
                Chọn video khác
              </Button>
            </div>
          ) : !sample ? (
            <p className="flex items-center gap-2 text-sm text-ink-muted" role="status">
              <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
              Đang tải video mẫu…
            </p>
          ) : step === 1 ? (
            <SampleSelectStep sampleId={sampleId} sample={sample} onBack={backToUpload} onStart={() => setStep(2)} />
          ) : step === 2 ? (
            <SampleProcessStep sampleId={sampleId} sample={sample} onDone={() => setStep(3)} />
          ) : (
            <SampleReadyStep sampleId={sampleId} sample={sample} />
          )
        ) : (
          step === 1 && <SelectAndConfirm preselect={preselect} onBack={() => setStep(0)} />
        )}
      </div>
    </main>
  );
}

function SelectAndConfirm({ preselect, onBack }: { preselect: string | null; onBack: () => void }) {
  const router = useRouter();
  const ids = { name: useId(), owner: useId(), origin: useId(), purpose: useId() };
  const [uploads, setUploads] = useState<UploadRecord[] | null>(null);
  const [selected, setSelected] = useState<string | null>(preselect);
  const [name, setName] = useState("");
  const [owner, setOwner] = useState("");
  const [origin, setOrigin] = useState<DataOrigin>("self_collected_no_pii");
  const [purpose, setPurpose] = useState("Dựng scene mô phỏng kho cho robot AMR");
  const [rights, setRights] = useState(false);
  const [anonymized, setAnonymized] = useState(false);
  const [retention, setRetention] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    const result = await listUploads();
    if (!result.ok) {
      setError(result.error.detail);
      return;
    }
    setUploads(result.data.uploads);
    const first = result.data.uploads.find((item) => item.upload_id === preselect) ?? result.data.uploads[0];
    if (first) {
      setSelected((current) => current ?? first.upload_id);
      setName((current) => current || first.original_name.replace(/\.[^.]+$/, ""));
    }
  }, [preselect]);

  useEffect(() => {
    // Nạp danh sách một lần khi vào bước; setState xảy ra sau await nên không đồng bộ trong effect.
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  const processing = useProcessingForm(true);
  const blocked = processing.evaluation?.blocking ?? false;
  const selectedUpload = uploads?.find((upload) => upload.upload_id === selected) ?? null;
  const supported = selectedUpload === null || canCreateScene(selectedUpload);
  const ready = Boolean(
    selected && supported && name.trim() && owner.trim() && purpose.trim() && rights && anonymized && retention && !blocked,
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !ready) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createSceneFromUpload(selected, name.trim(), {
        data_origin: origin,
        declared_owner: owner.trim(),
        declared_purpose: purpose.trim(),
        rights_to_use_confirmed: rights,
        anonymization_confirmed: anonymized,
        retention_acknowledged: retention,
      }, processing.values ?? undefined);
      router.push(`/scenes/${encodeURIComponent(created.job.job_id)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không tạo được scene");
      setSubmitting(false);
    }
  }

  if (uploads === null && !error) {
    return (
      <p className="flex items-center gap-2 text-sm text-ink-muted" role="status">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        Đang tải danh sách video…
      </p>
    );
  }
  if (uploads && uploads.length === 0) {
    return (
      <EmptyState
        icon={<Film aria-hidden />}
        title="Chưa có video nào"
        action={
          <Button onClick={onBack}>
            <ArrowLeft aria-hidden />
            Tải video lên
          </Button>
        }
      />
    );
  }

  return (
    <form onSubmit={submit} className="space-y-6">
      <Card className="p-5 sm:p-6">
        <h2 className="text-base font-semibold">Chọn video để xử lý</h2>
        <fieldset className="mt-4 space-y-2">
          <legend className="sr-only">Video đã tải lên</legend>
          {uploads?.map((upload) => (
            <label
              key={upload.upload_id}
              className={cn(
                "flex cursor-pointer items-center gap-4 rounded-xl border p-3 transition-colors duration-200",
                selected === upload.upload_id ? "border-ember bg-ember-soft/50" : "border-line hover:border-line-strong",
              )}
            >
              <input
                type="radio"
                name="upload"
                value={upload.upload_id}
                checked={selected === upload.upload_id}
                onChange={() => {
                  setSelected(upload.upload_id);
                  setName(upload.original_name.replace(/\.[^.]+$/, ""));
                }}
                className="size-4 accent-ember-strong"
              />
              <Film className="size-5 shrink-0 text-ink-muted" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{upload.original_name}</p>
                <p className="text-sm text-ink-muted">
                  {describeDetection(upload)} · {formatBytes(upload.size_bytes)} · {DATE.format(new Date(upload.received_at))}
                  {upload.project_ids.length > 0 && ` · đã dùng cho ${upload.project_ids.length} scene`}
                </p>
              </div>
            </label>
          ))}
        </fieldset>
        {!supported && (
          <Notice tone="ochre" className="mt-4">
            Máy chủ đã nhận diện file này là {selectedUpload ? describeDetection(selectedUpload) : "file 3DGS"}. Luồng dựng
            scene từ file 3DGS đang được làm; hiện chỉ video mới bắt đầu xử lý được.
          </Notice>
        )}
        <div className="mt-5">
          <label htmlFor={ids.name} className="text-sm font-medium">
            Tên scene
          </label>
          <input
            id={ids.name}
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={200}
            required
            className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30"
          />
        </div>
      </Card>

      <Card className="p-5 sm:p-6">
        <h2 className="text-base font-semibold">Xác nhận dữ liệu</h2>
        <p className="mt-1 text-sm text-ink-muted">
          Hệ thống chưa tự làm mờ khuôn mặt/biển số. Bạn xác nhận video phù hợp; lời xác nhận được lưu cùng scene.
        </p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field id={ids.owner} label="Người/đơn vị sở hữu dữ liệu">
            <input
              id={ids.owner}
              value={owner}
              onChange={(event) => setOwner(event.target.value)}
              maxLength={200}
              required
              placeholder="Ví dụ: Nhóm P-087"
              className={INPUT}
            />
          </Field>
          <Field id={ids.origin} label="Nguồn dữ liệu">
            <select id={ids.origin} value={origin} onChange={(event) => setOrigin(event.target.value as DataOrigin)} className={INPUT}>
              {ORIGINS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field id={ids.purpose} label="Mục đích sử dụng" className="sm:col-span-2">
            <input id={ids.purpose} value={purpose} onChange={(event) => setPurpose(event.target.value)} maxLength={500} required className={INPUT} />
          </Field>
        </div>
        <div className="mt-5 space-y-3">
          <Check checked={rights} onChange={setRights}>
            Tôi có quyền sử dụng video này cho mục đích trên.
          </Check>
          <Check checked={anonymized} onChange={setAnonymized}>
            Video <strong>không có khuôn mặt hoặc biển số</strong>, hoặc đã được làm mờ trước khi tải lên.
          </Check>
          <Check checked={retention} onChange={setRetention}>
            Tôi hiểu video gốc và kết quả được lưu trên máy chủ để dựng scene.
          </Check>
        </div>
      </Card>

      {processing.options && processing.values ? (
        <ProcessingSettings
          parameters={processing.options.parameters}
          values={processing.values}
          editable
          evaluation={processing.evaluation}
          capability={processing.options.capability}
          activePreset={processing.activePreset}
          onPreset={processing.applyPreset}
          onChange={processing.setValue}
          note={processing.options.resource_note}
        />
      ) : processing.error ? (
        <Notice tone="ochre">Không tải được bảng thông số: {processing.error}. Scene sẽ dùng cấu hình mặc định của máy chủ.</Notice>
      ) : null}

      {blocked && (
        <Notice tone="rust">
          Thông số hiện tại vượt cấu hình máy xử lý và có thể làm job bị crash. Giảm các ô tô đỏ hoặc chọn “Tối đa cho máy
          này”.
        </Notice>
      )}
      {error && <Notice tone="rust">{error}</Notice>}

      <div className="flex items-center justify-between gap-3">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft aria-hidden />
          Tải video khác
        </Button>
        <Button type="submit" size="lg" disabled={!ready || submitting}>
          {submitting ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <Play aria-hidden />}
          Bắt đầu xử lý
        </Button>
      </div>
    </form>
  );
}

const INPUT =
  "mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30";

function Field({ id, label, className, children }: { id: string; label: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={className}>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
    </div>
  );
}

function Check({ checked, onChange, children }: { checked: boolean; onChange: (value: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-3 text-sm text-ink">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        required
        className="mt-0.5 size-4 shrink-0 accent-ember-strong"
      />
      <span>{children}</span>
    </label>
  );
}
