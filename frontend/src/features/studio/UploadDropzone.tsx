"use client";

import { notifySuccess } from "@/components/studio/feedback";
import { Button, Notice, ProgressBar } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { GAUSSIAN_ACCEPT, LIDAR_ACCEPT, VIDEO_ACCEPT, rejectFileNameFor } from "@/features/studio/inputKinds";
import { errorMessage } from "@/lib/ui-error";
import { uploadPreparedVideo, uploadVideo, type UploadHandle } from "@/lib/api/studio";
import type { UploadRecord } from "@/lib/contracts/studio";
import type { VideoResolutionPreset } from "@/lib/contracts/videoPreparation";
import { VideoPreparationError, type VideoPreparationPhase } from "@/lib/media/video-normalization-core";
import { prepareVideoForUpload, type VideoPreparedArtifact, type VideoPreparationProgress } from "@/lib/media/video-normalization";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";

import { FileVideo, Upload, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

const VIDEO_PRESETS: { value: VideoResolutionPreset; label: string; detail: string }[] = [
  { value: "1080p", label: "1080p", detail: "tối đa 1920 × 1080 ngang / 1080 × 1920 dọc" },
  { value: "720p", label: "720p", detail: "mặc định · tối đa 1280 × 720 ngang / 720 × 1280 dọc" },
  { value: "480p", label: "480p", detail: "tối đa 854 × 480 ngang / 480 × 854 dọc" },
];

function phaseLabel(phase: VideoPreparationPhase): string {
  switch (phase) {
    case "hashing": return "Đang đọc và kiểm tra video gốc";
    case "probing": return "Đang kiểm tra khả năng xử lý";
    case "encoding": return "Đang tạo video theo độ phân giải đã chọn";
    case "verifying": return "Đang kiểm tra video và thời điểm frame";
  }
}

function rateLabel(rate: { numerator: number; denominator: number } | null): string {
  if (!rate) return "không có metadata FPS";
  return `${(rate.numerator / rate.denominator).toFixed(2)} FPS`;
}

function orientationLabel(width: number, height: number): string {
  if (height > width) return "dọc";
  if (width > height) return "ngang";
  return "vuông";
}

function audioPolicyLabel(disposition: VideoPreparedArtifact["manifest"]["audio_disposition"]): string {
  switch (disposition) {
    case "source_has_no_audio": return "video gốc không có âm thanh";
    case "preserved": return "đã giữ nguyên âm thanh";
    case "omitted_with_user_consent": return "đã bỏ âm thanh theo lựa chọn của bạn";
  }
}

/** Video được chuẩn bị và xem trước trước khi gửi; PLY/SOG/LiDAR giữ nguyên đường upload hiện tại. */
export function UploadDropzone({
  kind,
  onUploaded,
}: {
  kind: "video" | "gaussian" | "lidar";
  onUploaded: (record: UploadRecord) => void;
}) {
  const inputId = useId();
  const { me } = useAuth();
  const accountId = me?.user?.user_id ?? (me?.auth_required ? "anonymous" : "local");
  const [file, setFile] = useState<File | null>(null);
  const [prepared, setPrepared] = useState<VideoPreparedArtifact | null>(null);
  const preparedRef = useRef<VideoPreparedArtifact | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const previewUrlRef = useRef<string | null>(null);
  const [preset, setPreset] = useState<VideoResolutionPreset>("720p");
  const [preparing, setPreparing] = useState(false);
  const [prepareProgress, setPrepareProgress] = useState<VideoPreparationProgress | null>(null);
  const [omitAudioConsent, setOmitAudioConsent] = useState(false);
  const [needsAudioConsent, setNeedsAudioConsent] = useState(false);
  const [originalFallback, setOriginalFallback] = useState(false);
  const [pendingUploadRecord, setPendingUploadRecord] = useState<UploadRecord | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [progressName, setProgressName] = useState("");
  const [progressBytes, setProgressBytes] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadComplete, setUploadComplete] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const handle = useRef<UploadHandle | null>(null);
  const preparationAbort = useRef<AbortController | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      handle.current?.abort();
      preparationAbort.current?.abort();
      const artifact = preparedRef.current;
      preparedRef.current = null;
      if (artifact) void artifact.dispose().catch(() => undefined);
      const objectUrl = previewUrlRef.current;
      previewUrlRef.current = null;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, []);

  function clearPreview() {
    const objectUrl = previewUrlRef.current;
    previewUrlRef.current = null;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    setPreviewUrl(null);
  }

  function discardPrepared() {
    const artifact = preparedRef.current;
    preparedRef.current = null;
    clearPreview();
    setPrepared(null);
    setPendingUploadRecord(null);
    setPrepareProgress(null);
    setNeedsAudioConsent(false);
    setOmitAudioConsent(false);
    setOriginalFallback(false);
    if (artifact) void artifact.dispose().catch(() => undefined);
  }

  function startUpload(upload: UploadHandle, uploadName: string, uploadBytes: number, successMessage: string) {
    setProgress(0);
    setProgressName(uploadName);
    setProgressBytes(uploadBytes);
    setError(null);
    setUploading(true);
    setVerifying(false);
    handle.current = upload;
    upload.promise.then(
      (record) => {
        if (!mounted.current) return;
        handle.current = null;
        setUploading(false);
        setVerifying(false);
        if (kind === "video") setUploadComplete(true);
        setProgress(1);
        notifySuccess(successMessage);
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

  function start(candidate: File | undefined) {
    if (!candidate) return;
    const rejected = rejectFileNameFor(candidate.name, kind);
    if (rejected) {
      setError(rejected);
      return;
    }
    discardPrepared();
    setFile(candidate);
    setError(null);
    setProgress(null);
    setUploadComplete(false);
    setVerifying(false);
    setPendingUploadRecord(null);
    if (kind === "video") {
      setPreset("720p");
      setNeedsAudioConsent(false);
      return;
    }
    startUpload(uploadVideo(candidate, setProgress, () => setVerifying(true)), candidate.name, candidate.size, "Đã tải lên và kiểm tra file.");
  }

  async function prepareVideo(omitAudioWithConsent = omitAudioConsent) {
    if (!file || kind !== "video" || preparing || uploading) return;
    preparationAbort.current?.abort();
    const controller = new AbortController();
    preparationAbort.current = controller;
    setPreparing(true);
    setPrepareProgress({ phase: "hashing", progress: 0 });
    setError(null);
    setOriginalFallback(false);
    setNeedsAudioConsent(false);
    setOmitAudioConsent(omitAudioWithConsent);
    try {
      const artifact = await prepareVideoForUpload({
        source: file,
        preset,
        omitAudioWithConsent,
        signal: controller.signal,
        onProgress: setPrepareProgress,
      });
      if (!mounted.current) {
        await artifact.dispose();
        return;
      }
      preparedRef.current = artifact;
      const objectUrl = URL.createObjectURL(artifact.file);
      previewUrlRef.current = objectUrl;
      setPreviewUrl(objectUrl);
      setPrepared(artifact);
      setPendingUploadRecord(null);
      setOriginalFallback(false);
    } catch (cause: unknown) {
      if (!mounted.current) return;
      if (cause instanceof VideoPreparationError && cause.code === "cancelled") {
        setError("Đã hủy chuẩn bị; video gốc chưa được tải lên.");
      } else if (cause instanceof VideoPreparationError && cause.code === "audio_omission_required") {
        setNeedsAudioConsent(true);
        setOmitAudioConsent(false);
        setError("Video có âm thanh không tương thích. Bạn có thể đồng ý bỏ âm thanh rồi chuẩn bị lại.");
      } else {
        setError(errorMessage(cause, "Không thể chuẩn bị video; video gốc chưa được tải lên."));
        setOriginalFallback(true);
      }
    } finally {
      if (mounted.current) setPreparing(false);
      preparationAbort.current = null;
    }
  }

  function uploadPrepared() {
    if (!file || !prepared || uploading || preparing) return;
    const upload = uploadPreparedVideo(prepared, {
      accountId,
      existingRecord: pendingUploadRecord,
      onProgress: setProgress,
      onVerifying: () => setVerifying(true),
      onUploadedRecord: setPendingUploadRecord,
    });
    startUpload(upload, prepared.file.name, prepared.file.size, "Video đã tải lên và bản đồ frame đã được xác minh.");
  }

  function uploadOriginal() {
    if (!file || uploading || preparing) return;
    startUpload(uploadVideo(file, setProgress, () => setVerifying(true)), file.name, file.size, "Đã tải lên và kiểm tra file gốc.");
  }

  const outputIsLarger = prepared !== null && prepared.file.size > (file?.size ?? 0);
  const videoAccept = kind === "video" ? VIDEO_ACCEPT : kind === "lidar" ? LIDAR_ACCEPT : GAUSSIAN_ACCEPT;

  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          if (!uploading && !preparing) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!uploading && !preparing) start(event.dataTransfer.files[0]);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors duration-200 focus-within:ring-3 focus-within:ring-ember/40",
          dragging ? "border-ember bg-ember-soft/60" : "border-line-strong bg-paper-raised hover:border-ember/60",
          (uploading || preparing) && "pointer-events-none opacity-70",
        )}
      >
        <span className="grid size-12 place-items-center rounded-full bg-ember-soft text-ember-strong">
          <Upload className="size-5" aria-hidden />
        </span>
        <span className="mt-4 text-base font-semibold text-ink">
          {kind === "video" ? "Kéo video vào đây, hoặc bấm để chọn" : kind === "lidar" ? "Kéo gói LiDAR (.zip) vào đây, hoặc bấm để chọn" : "Kéo file 3DGS vào đây, hoặc bấm để chọn"}
        </span>
        <span className="mt-1 text-sm text-ink-muted">
          {kind === "video"
            ? "MP4/MOV · chọn độ phân giải, xem trước rồi mới tải lên · giữ nguyên tỉ lệ dọc/ngang"
            : kind === "lidar"
              ? "ZIP gồm quỹ đạo + calibration + thời điểm frame, cùng các scan .pcd hoặc một đám mây đã đăng ký"
              : "PLY/SOG hoặc ZIP gồm PLY + COLMAP · chỉ xem/chỉnh Gaussian và xuất file; không dựng collision hay phát hành"}
        </span>
        <input
          id={inputId}
          type="file"
          accept={videoAccept}
          className="sr-only"
          disabled={uploading || preparing}
          onChange={(event) => {
            start(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </label>

      {kind === "video" && file && !uploading && (
        <section className="mt-4 rounded-xl border border-line bg-paper-raised p-4" aria-label="Chuẩn bị video">
          <p className="truncate text-sm font-semibold text-ink">{file.name}</p>
          <p className="mt-1 text-sm text-ink-muted">Video gốc: {formatBytes(file.size)} · video gốc chỉ được gửi nếu bạn chọn rõ.</p>
          {uploadComplete ? (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-sage-soft p-3 text-sm text-sage" role="status">
              <span>Video đã tải lên và qua bước xác minh.</span>
              <Button variant="secondary" onClick={() => { discardPrepared(); setFile(null); setProgress(null); setUploadComplete(false); }}>
                Chọn video khác
              </Button>
            </div>
          ) : !prepared && (
            <>
              <fieldset className="mt-4">
                <legend className="text-sm font-semibold text-ink">Độ phân giải tối đa</legend>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  {VIDEO_PRESETS.map((option) => (
                    <label key={option.value} className="flex cursor-pointer items-start gap-2 rounded-lg border border-line p-3 text-sm">
                      <input
                        type="radio"
                        name={`${inputId}-preset`}
                        value={option.value}
                        checked={preset === option.value}
                        disabled={preparing}
                        onChange={() => setPreset(option.value)}
                      />
                      <span><strong>{option.label}</strong><span className="block text-xs text-ink-muted">{option.detail}</span></span>
                    </label>
                  ))}
                </div>
              </fieldset>
              {needsAudioConsent && (
                <label className="mt-3 flex items-start gap-2 text-sm text-ink">
                  <input
                    type="checkbox"
                    checked={omitAudioConsent}
                    onChange={(event) => setOmitAudioConsent(event.target.checked)}
                  />
                  <span>Tôi đồng ý bỏ toàn bộ âm thanh nếu không thể giữ nguyên trong video đã chuẩn bị.</span>
                </label>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <Button onClick={() => void prepareVideo()} disabled={preparing || (needsAudioConsent && !omitAudioConsent)}>
                  {needsAudioConsent && omitAudioConsent ? "Chuẩn bị và bỏ âm thanh" : "Chuẩn bị để xem trước"}
                </Button>
                {(originalFallback || needsAudioConsent) && (
                  <Button variant="secondary" onClick={uploadOriginal} disabled={preparing}>
                    Tải video gốc không nén
                  </Button>
                )}
              </div>
            </>
          )}

          {preparing && (
            <div className="mt-4" role="status" aria-live="polite">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span>{prepareProgress ? phaseLabel(prepareProgress.phase) : "Đang chuẩn bị video"}</span>
                <span className="value-tech">{Math.round((prepareProgress?.progress ?? 0) * 100)}%</span>
              </div>
              <ProgressBar value={prepareProgress?.progress ?? 0} label="Tiến độ chuẩn bị video" className="mt-2" />
              <Button variant="ghost" className="mt-2" onClick={() => preparationAbort.current?.abort()}>
                <X aria-hidden /> Hủy chuẩn bị
              </Button>
            </div>
          )}

          {prepared && (
            <div className="mt-4 space-y-3">
              {previewUrl && (
                <video
                  controls
                  preload="metadata"
                  src={previewUrl}
                  aria-label="Xem trước video đã chuẩn bị"
                  className="mx-auto max-h-80 max-w-full rounded-lg bg-media-preview-surface object-contain"
                />
              )}
              <div className="text-sm text-ink-muted">
                <p>Nguồn: {prepared.manifest.source_video.display_width} × {prepared.manifest.source_video.display_height} ({orientationLabel(prepared.manifest.source_video.display_width, prepared.manifest.source_video.display_height)}) · {rateLabel(prepared.manifest.source_video.frame_rate)}.</p>
                <p>Bản xem trước: {formatBytes(prepared.file.size)} · {prepared.manifest.prepared_video.display_width} × {prepared.manifest.prepared_video.display_height} ({orientationLabel(prepared.manifest.prepared_video.display_width, prepared.manifest.prepared_video.display_height)}) · {rateLabel(prepared.manifest.prepared_video.frame_rate)}, tối đa 30 FPS.</p>
                <p>Âm thanh: {audioPolicyLabel(prepared.manifest.audio_disposition)}.</p>
                {outputIsLarger
                  ? <p className="mt-1 text-ochre-strong">Bản đã chuẩn bị lớn hơn video gốc {Math.round((prepared.file.size / file.size - 1) * 100)}%. Chọn rõ một trong hai bản trước khi gửi.</p>
                  : <p className="mt-1">Giảm {Math.max(0, Math.round((1 - prepared.file.size / file.size) * 100))}% dung lượng theo số byte thực tế.</p>}
                <p className="mt-1">Khung hình dọc/ngang giữ tỉ lệ; video đã chuẩn bị được gửi sau khi bạn bấm nút bên dưới.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button onClick={uploadPrepared} disabled={uploadComplete}>
                  {pendingUploadRecord ? "Tiếp tục xác minh video" : "Tải bản đã xem trước lên"}
                </Button>
                {outputIsLarger && <Button variant="secondary" onClick={uploadOriginal} disabled={uploadComplete}>Tải video gốc không nén</Button>}
                <Button variant="ghost" onClick={() => { setError(null); discardPrepared(); }} disabled={uploadComplete}>Chọn độ phân giải khác</Button>
              </div>
            </div>
          )}
        </section>
      )}

      {progress !== null && (uploading || progress >= 1) && (
        <div className="mt-4 flex items-center gap-4 rounded-xl border border-line bg-paper-raised p-4">
          <FileVideo className="size-5 shrink-0 text-ink-muted" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate font-medium">{progressName}</span>
              <span className="shrink-0 value-tech text-ink-subtle">
                {verifying ? "Máy chủ đang kiểm tra file và bản đồ frame…" : progress >= 1 ? "Đã tải xong" : `${Math.round(progress * 100)}% · ${formatBytes(progressBytes)}`}
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
