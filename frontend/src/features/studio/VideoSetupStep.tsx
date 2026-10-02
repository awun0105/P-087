"use client";

import { errorMessage } from "@/lib/ui-error";

import { ArrowLeft, Film, Loader2, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import { Badge, Button, Card, EmptyState, Notice } from "@/components/studio/primitives";
import { canCreateScene, describeDetection } from "@/features/studio/inputKinds";
import { LidarPackageSection, NO_LIDAR, lidarAttachment, lidarBlocker, type LidarChoice } from "@/features/studio/LidarPackageSection";
import { ProcessingSettings } from "@/features/studio/ProcessingSettings";
import { useProcessingForm } from "@/features/studio/useProcessingForm";
import { createSceneFromUpload, listUploads } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { DataOrigin, UploadRecord } from "@/lib/contracts/studio";
import { useAuth } from "@/features/studio/AuthProvider";
import { useSessionDraft } from "@/features/studio/drafts";
import { EMPTY_SETUP, parseSetupDraft, type SetupDraft } from "@/features/studio/setup-draft";
import { notifySuccess, FieldError } from "@/components/studio/feedback";
import { formatBytes } from "@/lib/format";

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" });

const ORIGINS: { value: DataOrigin; label: string }[] = [
  { value: "self_collected_no_pii", label: "Tự quay, không có người/biển số" },
  { value: "anonymized", label: "Đã làm mờ khuôn mặt/biển số" },
  { value: "public_or_synthetic", label: "Dữ liệu công khai hoặc tổng hợp" },
];

export function VideoSetupStep({ preselect, onBack }: { preselect: string | null; onBack: () => void }) {
  const router = useRouter();
  const ids = { name: useId(), owner: useId(), origin: useId(), purpose: useId() };
  const [uploads, setUploads] = useState<UploadRecord[] | null>(null);
  // Mọi upload (gồm gói LiDAR) và lựa chọn LiDAR của scene này; LiDAR là tuỳ chọn nên mặc định không dùng.
  const [allUploads, setAllUploads] = useState<UploadRecord[]>([]);
  const [lidar, setLidar] = useState<LidarChoice>(NO_LIDAR);
  const { me } = useAuth();
  const actor = me?.user?.user_id ?? (me?.auth_required ? "guest" : "local");
  const { value: draft, setValue: setDraft, ready: draftReady, clear } = useSessionDraft("video:v1:" + actor, { ...EMPTY_SETUP, selected: preselect }, parseSetupDraft);
  const { selected, name, owner, origin, purpose, rights, anonymized, retention } = draft;
  const field = <K extends keyof SetupDraft,>(key: K) => (value: SetupDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const setName = field("name"), setOwner = field("owner"), setOrigin = field("origin"), setPurpose = field("purpose");
  const setRights = field("rights"), setAnonymized = field("anonymized"), setRetention = field("retention");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    const result = await listUploads();
    if (!result.ok) {
      setError(errorMessage(result.error));
      return;
    }
    const videos = result.data.uploads.filter(canCreateScene);
    setUploads(videos);
    setAllUploads(result.data.uploads);
    setError(null);
    setDraft((current) => {
      const first = videos.find((item) => item.upload_id === preselect) ?? videos.find((item) => item.upload_id === current.selected) ?? videos[0];
      const changed = current.selected !== (first?.upload_id ?? null);
      return { ...current, selected: first?.upload_id ?? null, name: changed || !current.name ? first?.original_name.replace(/\.[^.]+$/, "") ?? "" : current.name,
        ...(changed ? { rights: false, anonymized: false, retention: false } : {}) };
    });
  }, [preselect, setDraft]);

  useEffect(() => {
    // Nạp danh sách một lần khi vào bước; setState xảy ra sau await nên không đồng bộ trong effect.
    if (!draftReady) return;
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, draftReady]);

  const processing = useProcessingForm(true, draft.processing, draftReady);
  useEffect(() => {
    if (!draftReady || !processing.values) return;
    setDraft((current) => JSON.stringify(current.processing) === JSON.stringify(processing.values) ? current : { ...current, processing: processing.values });
  }, [draftReady, processing.values, setDraft]);
  const blocked = processing.evaluation?.blocking ?? false;
  const selectedUpload = uploads?.find((upload) => upload.upload_id === selected) ?? null;
  const supported = selectedUpload === null || canCreateScene(selectedUpload);
  // Lý do khoá nút, hiện ngay cạnh CTA (STUDIO_UX_SPEC.md §7.4) thay vì nút xám không giải thích.
  const missing = [
    !selected && "Chưa chọn video",
    selected && !supported && "Máy chủ nhận diện file này không phải video",
    !name.trim() && "Chưa đặt tên scene",
    !owner.trim() && "Chưa khai người/đơn vị sở hữu dữ liệu",
    !purpose.trim() && "Chưa khai mục đích sử dụng",
    !(rights && anonymized && retention) && "Chưa tick đủ 3 xác nhận dữ liệu",
    lidarBlocker(lidar),
    blocked && "Thông số vượt cấu hình máy xử lý",
    processing.loading && "Đang tải cấu hình xử lý",
    processing.evaluating && "Đang kiểm tra thông số xử lý",
    processing.options && processing.error && "Chưa kiểm tra được thông số; thử lại hoặc đổi preset",
  ].filter((reason): reason is string => Boolean(reason));
  const ready = missing.length === 0;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !ready || submitting) return;
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
      }, processing.values ?? undefined, lidarAttachment(lidar));
      clear();
      notifySuccess("Đã tạo job. Bạn có thể theo dõi tại Tiến trình.");
      router.push(`/scenes/${encodeURIComponent(created.job.job_id)}`);
    } catch (cause) {
      setError(errorMessage(cause, "Không tạo được scene"));
      setSubmitting(false);
    }
  }

  if (!draftReady) return <p role="status" className="text-sm text-ink-muted">Đang khôi phục form…</p>;
  if (uploads === null && error) {
    return <Notice tone="rust">Không tải được danh sách video: {error} <Button size="sm" variant="secondary" onClick={() => void load()}>Thử lại</Button></Notice>;
  }
  if (uploads === null) {
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
        <h2 className="text-base font-bold">Chọn video để xử lý</h2>
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
                  setDraft((current) => ({ ...current, selected: upload.upload_id, name: upload.original_name.replace(/\.[^.]+$/, ""), rights: false, anonymized: false, retention: false }));
                }}
                className="size-4 accent-ember-strong"
              />
              <Film className="size-5 shrink-0 text-ink-muted" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{upload.original_name}</p>
                <p className="text-sm text-ink-muted">
                  {describeDetection(upload)} · {formatBytes(upload.size_bytes)} · {DATE.format(new Date(upload.received_at))}
                  {upload.uploaded_by && ` · tải lên bởi ${upload.uploaded_by.display_name}`}
                  {upload.project_ids.length > 0 && ` · đã dùng cho ${upload.project_ids.length} scene`}
                </p>
              </div>
            </label>
          ))}
        </fieldset>
        <div className="mt-5">
          <label htmlFor={ids.name} className="text-sm font-medium">
            Tên scene
          </label>
          <input
            id={ids.name}
            aria-invalid={touched.name && !name.trim()} aria-describedby={touched.name && !name.trim() ? ids.name + "-error" : undefined}
            onBlur={() => setTouched((old) => ({ ...old, name: true }))}
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={200}
            required
            className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30"
          />
          <FieldError id={ids.name + "-error"} message={touched.name && !name.trim() ? "Nhập tên scene." : null} />
        </div>
      </Card>

      <LidarPackageSection
        uploads={allUploads}
        choice={lidar}
        onChange={setLidar}
        onUploaded={(record) => setAllUploads((current) => [record, ...current.filter((item) => item.upload_id !== record.upload_id)])}
      />

      <Card className="p-5 sm:p-6">
        <h2 className="flex flex-wrap items-center gap-2 text-base font-bold">
          Xác nhận dữ liệu
          <Badge tone="ochre">Tự khai — chưa qua QA</Badge>
        </h2>
        <p className="mt-1 text-sm text-ink-muted">
          Hệ thống chưa tự làm mờ khuôn mặt/biển số. Bạn xác nhận video phù hợp; lời xác nhận được lưu cùng scene.
        </p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field id={ids.owner} label="Người/đơn vị sở hữu dữ liệu">
            <input
              id={ids.owner}
              onBlur={() => setTouched((old) => ({ ...old, owner: true }))}
              aria-invalid={touched.owner && !owner.trim()} aria-describedby={touched.owner && !owner.trim() ? ids.owner + "-error" : undefined}
              value={owner}
              onChange={(event) => setOwner(event.target.value)}
              maxLength={200}
              required
              placeholder="Ví dụ: Nhóm P-087"
              className={INPUT}
            />
            <FieldError id={ids.owner + "-error"} message={touched.owner && !owner.trim() ? "Nhập người hoặc đơn vị sở hữu dữ liệu." : null} />
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
            <input id={ids.purpose} value={purpose} onChange={(event) => setPurpose(event.target.value)} onBlur={() => setTouched((old) => ({ ...old, purpose: true }))} aria-invalid={touched.purpose && !purpose.trim()} aria-describedby={touched.purpose && !purpose.trim() ? ids.purpose + "-error" : undefined} maxLength={500} required className={INPUT} />
            <FieldError id={ids.purpose + "-error"} message={touched.purpose && !purpose.trim() ? "Nhập mục đích sử dụng dữ liệu." : null} />
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
      ) : null}
      {processing.error && <Notice tone={processing.options ? "rust" : "ochre"}>
        {processing.error} {!processing.options && "Có thể tiếp tục với cấu hình mặc định của máy chủ."}
        <Button size="sm" variant="secondary" onClick={processing.retry}>Thử lại thông số</Button>
      </Notice>}

      {blocked && (
        <Notice tone="rust">
          Thông số hiện tại vượt cấu hình máy xử lý và có thể làm job bị crash. Giảm các ô tô đỏ hoặc chọn “Tối đa cho máy
          này”.
        </Notice>
      )}
      {error && <Notice tone="rust">{error}</Notice>}

      <Card className="p-5 sm:p-6">
        <h2 className="text-base font-bold">Tóm tắt trước khi xử lý</h2>
        <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="text-ink-muted">Video</dt>
          <dd>{selectedUpload ? `${selectedUpload.original_name} · ${describeDetection(selectedUpload)} · ${formatBytes(selectedUpload.size_bytes)}` : "Chưa chọn"}</dd>
          <dt className="text-ink-muted">LiDAR</dt>
          <dd>{lidar.uploadId ? (allUploads.find((item) => item.upload_id === lidar.uploadId)?.original_name ?? "Đã chọn") + " · tỉ lệ mét từ LiDAR" : "Không dùng · tỉ lệ mét ước lượng hoặc đo tay"}</dd>
          <dt className="text-ink-muted">Tên scene</dt>
          <dd>{name.trim() || "Chưa đặt"}</dd>
          <dt className="text-ink-muted">Nguồn dữ liệu</dt>
          <dd>{ORIGINS.find((item) => item.value === origin)?.label} · tự khai</dd>
          <dt className="text-ink-muted">Thông số</dt>
          <dd>{processing.activePreset ? "Theo preset đã chọn" : processing.values ? "Tuỳ chỉnh" : "Mặc định của máy chủ"}</dd>
        </dl>
        {missing.length > 0 && (
          <div className="mt-4 text-sm">
            <p className="font-medium text-ochre">Chưa bắt đầu được vì:</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-muted">
              {missing.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <p className="text-xs text-ink-muted">Form được giữ trong phiên tab. <button type="button" className="font-medium text-ember-strong" onClick={() => { clear(); setDraft({ ...EMPTY_SETUP, selected }); processing.applyPreset("minimum_quality"); }}>Bỏ bản nháp</button></p>
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
