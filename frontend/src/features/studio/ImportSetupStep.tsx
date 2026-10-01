"use client";

import { ArrowLeft, Box, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import { Button, Card, EmptyState, Notice } from "@/components/studio/primitives";
import { canCreateScene, describeDetection } from "@/features/studio/inputKinds";
import { createImport, listUploads } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { UploadRecord } from "@/lib/contracts/studio";
import { formatBytes } from "@/lib/format";

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" });
const INPUT = "mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30";

/** Import 3DGS có bước đặt tên riêng; không mang khai báo video hay preset reconstruction sang nhánh này. */
export function ImportSetupStep({ preselect, onBack }: { preselect: string | null; onBack: () => void }) {
  const router = useRouter();
  const nameId = useId();
  const [uploads, setUploads] = useState<UploadRecord[] | null>(null);
  const [selected, setSelected] = useState<string | null>(preselect);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    const result = await listUploads();
    if (!result.ok) {
      setError(result.error.detail);
      return;
    }
    const gaussian = result.data.uploads.filter((record) => !canCreateScene(record));
    setUploads(gaussian);
    setError(null);
    const first = gaussian.find((record) => record.upload_id === preselect) ?? gaussian[0];
    setSelected((current) => gaussian.some((record) => record.upload_id === current) ? current : first?.upload_id ?? null);
    if (first) {
      setName((current) => current || first.original_name.replace(/\.[^.]+$/, ""));
    }
  }, [preselect]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !name.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createImport(selected, name.trim());
      router.push(`/imports/${encodeURIComponent(created.import_id)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không mở được scene 3DGS");
      setSubmitting(false);
    }
  }

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
      <Notice tone="ochre">
        Scene import chỉ xem và chỉnh Gaussian trong editor; bản chỉnh sửa chỉ xuất ra PLY/SOG. Không có xác nhận tỉ lệ mét, collision, validation hay release.
      </Notice>
      <Card className="space-y-5 p-5 sm:p-6">
        <fieldset className="space-y-2">
          <legend className="mb-3 text-base font-semibold">Chọn file 3DGS đã tải</legend>
          {uploads.map((upload) => (
            <label key={upload.upload_id} className={cn("flex cursor-pointer items-start gap-3 rounded-xl border p-3", selected === upload.upload_id ? "border-ember bg-ember-soft/50" : "border-line hover:border-line-strong")}>
              <input type="radio" name="gaussian-upload" value={upload.upload_id} checked={selected === upload.upload_id} onChange={() => { setSelected(upload.upload_id); setName(upload.original_name.replace(/\.[^.]+$/, "")); }} className="mt-1 size-4 accent-ember-strong" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{upload.original_name}</span>
                <span className="block text-xs text-ink-muted">{describeDetection(upload)} · {formatBytes(upload.size_bytes)} · {DATE.format(new Date(upload.received_at))}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div>
          <label htmlFor={nameId} className="text-sm font-medium">Tên scene import</label>
          <input id={nameId} value={name} onChange={(event) => setName(event.target.value)} maxLength={200} required className={INPUT} />
        </div>
      </Card>
      {error && <Notice tone="rust">{error}</Notice>}
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
