"use client";

import { errorMessage } from "@/lib/ui-error";

import { ArrowLeft, Box, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import { Button, Card, EmptyState, Notice } from "@/components/studio/primitives";
import { canCreateScene, describeDetection } from "@/features/studio/inputKinds";
import { createImport, listUploads } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { UploadRecord } from "@/lib/contracts/studio";
import { useAuth } from "@/features/studio/AuthProvider";
import { useSessionDraft } from "@/features/studio/drafts";
import { EMPTY_SETUP, parseSetupDraft } from "@/features/studio/setup-draft";
import { notifySuccess, HelpDetails, FieldError } from "@/components/studio/feedback";
import { formatBytes } from "@/lib/format";

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" });
const INPUT = "mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30";

/** Import 3DGS có bước đặt tên riêng; không mang khai báo video hay preset reconstruction sang nhánh này. */
export function ImportSetupStep({ preselect, onBack }: { preselect: string | null; onBack: () => void }) {
  const router = useRouter();
  const nameId = useId();
  const [uploads, setUploads] = useState<UploadRecord[] | null>(null);
  const { me } = useAuth();
  const actor = me?.user?.user_id ?? (me?.auth_required ? "guest" : "local");
  const { value: draft, setValue: setDraft, ready: draftReady, clear } = useSessionDraft("gaussian:v1:" + actor, { ...EMPTY_SETUP, selected: preselect }, parseSetupDraft);
  const { selected, name } = draft;
  const setName = (name: string) => setDraft((current) => ({ ...current, name }));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [touched, setTouched] = useState(false);

  const load = useCallback(async () => {
    const result = await listUploads();
    if (!result.ok) {
      setError(errorMessage(result.error));
      return;
    }
    const gaussian = result.data.uploads.filter((record) => !canCreateScene(record));
    setUploads(gaussian);
    setError(null);
    setDraft((current) => {
      const first = gaussian.find((item) => item.upload_id === preselect) ?? gaussian.find((item) => item.upload_id === current.selected) ?? gaussian[0];
      return { ...current, selected: first?.upload_id ?? null, name: current.selected !== first?.upload_id || !current.name ? first?.original_name.replace(/\.[^.]+$/, "") ?? "" : current.name };
    });
  }, [preselect, setDraft]);

  useEffect(() => {
    if (!draftReady) return;
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load, draftReady]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !name.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createImport(selected, name.trim());
      clear();
      notifySuccess("Đã tạo scene import. Máy chủ đang chuẩn bị bản xem.");
      router.push(`/imports/${encodeURIComponent(created.import_id)}`);
    } catch (cause) {
      setError(errorMessage(cause, "Không mở được scene 3DGS"));
      setSubmitting(false);
    }
  }

  if (!draftReady) return <p role="status" className="text-sm text-ink-muted">Đang khôi phục form…</p>;
  if (uploads === null) {
    return error ? (
      <Notice tone="rust">Không tải được danh sách file: {error} <Button size="sm" onClick={() => void load()}>Thử lại</Button></Notice>
    ) : <p role="status" className="text-sm text-ink-muted">Đang tải danh sách file 3DGS…</p>;
  }
  if (uploads.length === 0) {
    return <EmptyState icon={<Box aria-hidden />} title="Chưa có file 3DGS" action={<Button onClick={onBack}>Tải PLY/ZIP lên</Button>}>
      File đã tải lên được máy chủ nhận diện là 3DGS sẽ xuất hiện ở đây.
    </EmptyState>;
  }
  return (
    <form onSubmit={submit} className="space-y-5">
      <HelpDetails title="Giới hạn của scene import">
        Scene import chỉ xem và chỉnh Gaussian trong editor; bản chỉnh sửa chỉ xuất ra PLY/SOG. Không có xác nhận tỉ lệ mét, collision, validation hay release.
      </HelpDetails>
      <Card className="space-y-5 p-5 sm:p-6">
        <fieldset className="space-y-2">
          <legend className="mb-3 text-base font-semibold">Chọn file 3DGS đã tải</legend>
          {uploads.map((upload) => (
            <label key={upload.upload_id} className={cn("flex cursor-pointer items-start gap-3 rounded-xl border p-3", selected === upload.upload_id ? "border-ember bg-ember-soft/50" : "border-line hover:border-line-strong")}>
              <input type="radio" name="gaussian-upload" value={upload.upload_id} checked={selected === upload.upload_id} onChange={() => { setDraft((current) => ({ ...current, selected: upload.upload_id, name: upload.original_name.replace(/\.[^.]+$/, "") })); }} className="mt-1 size-4 accent-ember-strong" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{upload.original_name}</span>
                <span className="block text-xs text-ink-muted">{describeDetection(upload)} · {formatBytes(upload.size_bytes)} · {DATE.format(new Date(upload.received_at))}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div>
          <label htmlFor={nameId} className="text-sm font-medium">Tên scene import</label>
          <input id={nameId} value={name} onChange={(event) => setName(event.target.value)} onBlur={() => setTouched(true)} aria-invalid={touched && !name.trim()} aria-describedby={touched && !name.trim() ? nameId + "-error" : undefined} maxLength={200} required className={INPUT} />
          <FieldError id={nameId + "-error"} message={touched && !name.trim() ? "Nhập tên scene import." : null} />
        </div>
      </Card>
      {error && <Notice tone="rust">{error}</Notice>}
      <p className="text-xs text-ink-muted">Form được giữ trong phiên tab. <button type="button" className="font-medium text-ember-strong" onClick={() => { clear(); setDraft({ ...EMPTY_SETUP, selected }); }}>Bỏ bản nháp</button></p>
      <div className="flex items-center justify-between gap-3">
        <Button variant="ghost" onClick={onBack}><ArrowLeft aria-hidden /> Chọn file khác</Button>
        <Button type="submit" size="lg" disabled={!selected || !name.trim() || submitting}>
          {submitting ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <Box aria-hidden />}
          Mở scene import
        </Button>
      </div>
    </form>
  );
}
