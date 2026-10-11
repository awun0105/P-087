"use client";

import { notifySuccess } from "@/components/studio/feedback";
import { Button, Notice, ProgressBar } from "@/components/studio/primitives";
import { GAUSSIAN_ACCEPT, rejectGaussianFileName } from "@/features/studio/inputKinds";
import { errorMessage } from "@/lib/ui-error";
import { uploadVideo, type UploadHandle } from "@/lib/api/studio";
import type { UploadRecord } from "@/lib/contracts/studio";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";

import { Box, Upload, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

/**
 * Upload một file 3DGS cho nhánh "Mở 3DGS có sẵn". Video và mọi sidecar đi qua khung tải input
 * chung (`UnifiedInputFlow`), nơi có bước chuẩn bị video và nhận diện nhiều file cùng lúc.
 */
export function UploadDropzone({ onUploaded }: { onUploaded: (record: UploadRecord) => void }) {
  const inputId = useId();
  const [progress, setProgress] = useState<number | null>(null);
  const [progressName, setProgressName] = useState("");
  const [progressBytes, setProgressBytes] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const handle = useRef<UploadHandle | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      handle.current?.abort();
    };
  }, []);

  function start(candidate: File | undefined) {
    if (!candidate) return;
    const rejected = rejectGaussianFileName(candidate.name);
    if (rejected) {
      setError(rejected);
      return;
    }
    setProgress(0);
    setProgressName(candidate.name);
    setProgressBytes(candidate.size);
    setError(null);
    setUploading(true);
    setVerifying(false);
    const upload = uploadVideo(candidate, setProgress, () => setVerifying(true));
    handle.current = upload;
    upload.promise.then(
      (record) => {
        if (!mounted.current) return;
        handle.current = null;
        setUploading(false);
        setVerifying(false);
        setProgress(1);
        notifySuccess("Đã tải lên và kiểm tra file.");
        onUploaded(record);
      },
      (cause: unknown) => {
        if (!mounted.current) return;
        handle.current = null;
        setUploading(false);
        setVerifying(false);
        setProgress(null);
        setError(errorMessage(cause, "Tải lên thất bại"));
      },
    );
  }

  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          if (!uploading) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!uploading) start(event.dataTransfer.files[0]);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors duration-200 focus-within:ring-3 focus-within:ring-ember/40",
          dragging ? "border-ember bg-ember-soft/60" : "border-line-strong bg-paper-raised hover:border-ember/60",
          uploading && "pointer-events-none opacity-70",
        )}
      >
        <span className="grid size-12 place-items-center rounded-full bg-ember-soft text-ember-strong">
          <Upload className="size-5" aria-hidden />
        </span>
        <span className="mt-4 text-base font-semibold text-ink">Kéo file 3DGS vào đây, hoặc bấm để chọn</span>
        <span className="mt-1 text-sm text-ink-muted">
          PLY/SOG hoặc ZIP gồm PLY + COLMAP · chỉ xem/chỉnh Gaussian và xuất file; không dựng collision hay phát hành
        </span>
        <input
          id={inputId}
          type="file"
          accept={GAUSSIAN_ACCEPT}
          className="sr-only"
          disabled={uploading}
          onChange={(event) => {
            start(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </label>

      {progress !== null && (uploading || progress >= 1) && (
        <div className="mt-4 flex items-center gap-4 rounded-xl border border-line bg-paper-raised p-4">
          <Box className="size-5 shrink-0 text-ink-muted" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate font-medium">{progressName}</span>
              <span className="shrink-0 value-tech text-ink-subtle">
                {verifying ? "Máy chủ đang kiểm tra file…" : progress >= 1 ? "Đã tải xong" : `${Math.round(progress * 100)}% · ${formatBytes(progressBytes)}`}
              </span>
            </div>
            <ProgressBar value={progress} label={`Tải lên ${progressName}`} className="mt-2" />
          </div>
          {uploading && (
            <Button variant="ghost" size="icon" aria-label="Hủy tải lên" onClick={() => handle.current?.abort()}>
              <X aria-hidden />
            </Button>
          )}
        </div>
      )}
      {error && <Notice tone="rust" className="mt-4">{error}</Notice>}
    </div>
  );
}
