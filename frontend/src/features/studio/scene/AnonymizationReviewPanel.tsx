"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { notifySuccess } from "@/components/studio/feedback";
import { Button, Notice } from "@/components/studio/primitives";
import { acceptAnonymization, getAnonymizationReview, redactedFrameUrl, type AnonymizationReview } from "@/lib/api/anonymization";
import { errorMessage } from "@/lib/ui-error";

const KIND_LABEL: Record<string, string> = { face: "khuôn mặt", license_plate: "biển số" };

/**
 * Job đã che khuôn mặt/biển số và đang dừng trước bước dựng 3D (AUD-18). Người upload xem các frame có vùng bị che
 * rồi xác nhận; không đồng ý thì huỷ job bằng nút huỷ sẵn có của tab. Máy chỉ che những gì nó phát hiện được, nên
 * lời nhắc nói rõ người xem cần tự kiểm cả phần còn sót.
 */
export function AnonymizationReviewPanel({ jobId, canAccept, onAccepted }: { jobId: string; canAccept: boolean; onAccepted: () => void }) {
  const [review, setReview] = useState<AnonymizationReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getAnonymizationReview(jobId, controller.signal).then(setReview, (cause: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(cause, "Không tải được bản đã che"));
    });
    return () => controller.abort();
  }, [jobId]);

  async function accept() {
    if (!review || busy) return;
    setBusy(true);
    setError(null);
    try {
      await acceptAnonymization(jobId, review.frame_set_checksum);
      notifySuccess("Đã xác nhận bản đã che. Hệ thống tiếp tục dựng 3D.");
      onAccepted();
    } catch (cause) {
      setError(errorMessage(cause, "Không xác nhận được bản đã che"));
      setBusy(false);
    }
  }

  return (
    <div className="mb-5 space-y-3" data-testid="anonymization-review">
      <div>
        <h3 className="text-base font-semibold">Xem bản đã che trước khi dựng 3D</h3>
        <p className="mt-1 text-sm text-ink-muted">
          Xác nhận để dựng 3D từ các ảnh đã che. Ảnh gốc chưa che đã được xoá.
        </p>
      </div>
      {error && <Notice tone="rust">{error}</Notice>}
      {review === null && !error && <p role="status" className="text-sm text-ink-muted">Đang tải bản đã che…</p>}
      {review && (
        <>
          <p className="text-sm">
            {review.frames.length === 0
              ? `Không phát hiện khuôn mặt hay biển số nào trong ${review.frame_count} frame.`
              : `Đã che ${review.frames.length} trên ${review.frame_count} frame. Vùng bị che được tô kín một màu.`}
          </p>
          <Notice tone="ochre">
            Công cụ tự động có thể bỏ sót. Nếu còn khuôn mặt hoặc biển số chưa che, hãy huỷ và quay lại video.
          </Notice>
          {review.frames.length > 0 && (
            <ul className="grid max-h-[28rem] grid-cols-2 gap-3 overflow-y-auto sm:grid-cols-3">
              {review.frames.map((frame) => (
                <li key={frame.frame_name} className="space-y-1">
                  {/* eslint-disable-next-line @next/next/no-img-element -- ảnh riêng tư qua API có cookie, không qua bộ tối ưu ảnh */}
                  <img src={redactedFrameUrl(jobId, frame.frame_name)} alt={`Frame ${frame.frame_name} đã che`} width={frame.width} height={frame.height} loading="lazy" className="h-auto w-full rounded-lg border border-line" />
                  <p className="text-xs text-ink-muted">
                    {frame.frame_name} · {frame.regions.length} vùng ({[...new Set(frame.regions.map((region) => KIND_LABEL[region.kind] ?? region.kind))].join(", ")})
                  </p>
                </li>
              ))}
            </ul>
          )}
          {canAccept && review.state === "awaiting" && (
            <div className="flex justify-end">
              <Button size="sm" disabled={busy} onClick={accept}><Check aria-hidden />Xác nhận và dựng 3D</Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
