"use client";

import { useEffect, useState } from "react";

import { boxesKey, toCommandBoxes, type EditableBox } from "@/features/studio/region/box-model";
import { ApiError } from "@/lib/api/client";
import { previewObjectRegion, type RegionPreview } from "@/lib/api/studio";

/** Chờ sau thay đổi cuối trước khi gọi preview; kéo liên tục chỉ tạo một yêu cầu. */
export const PREVIEW_DEBOUNCE_MS = 250;

/** Khoá của tập box và claim. Kết quả preview chỉ hợp lệ khi khoá của nó trùng khoá hiện tại. */
export function regionKey(boxes: readonly EditableBox[], claimFrom: readonly string[]): string {
  return `${boxesKey([...boxes])}|${[...claimFrom].sort().join(",")}`;
}

export interface RegionPreviewInput {
  jobId: string;
  objectId: string;
  expectedRevision: string;
  membershipChecksum: string;
  boxes: EditableBox[];
  claimFrom: string[];
  /** Tắt khi box không hợp lệ: không gọi preview. */
  enabled: boolean;
}

interface PreviewState {
  key: string;
  preview: RegionPreview | null;
  error: string | null;
}

/**
 * Xem trước vùng sau khi box đổi. Chờ `PREVIEW_DEBOUNCE_MS` sau thay đổi cuối; yêu cầu đang chờ bị huỷ khi có thay đổi
 * mới. `preview` chỉ trả về kết quả của đúng khoá hiện tại, nên kết quả của box cũ không bao giờ hiện như của box mới.
 */
export function useRegionPreview(input: RegionPreviewInput) {
  const { jobId, objectId, expectedRevision, membershipChecksum, boxes, claimFrom, enabled } = input;
  // Khoá gồm cả revision và checksum: đổi scene hoặc membership thì kết quả cũ không còn hợp lệ.
  const key = `${regionKey(boxes, claimFrom)}|${expectedRevision}|${membershipChecksum}`;
  const [state, setState] = useState<PreviewState | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewObjectRegion(
        jobId,
        objectId,
        {
          expected_scene_revision: expectedRevision,
          membership_checksum: membershipChecksum,
          boxes: toCommandBoxes(boxes),
          claim_from: [...claimFrom],
        },
        controller.signal,
      ).then(
        (result) => {
          if (!controller.signal.aborted) setState({ key, preview: result, error: null });
        },
        (cause: unknown) => {
          if (controller.signal.aborted) return;
          const message = cause instanceof ApiError ? cause.detail : "Không xem trước được vùng.";
          setState({ key, preview: null, error: message });
        },
      );
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [jobId, objectId, expectedRevision, membershipChecksum, boxes, claimFrom, key, enabled]);

  const current = state !== null && state.key === key ? state : null;
  return {
    key,
    preview: current?.preview ?? null,
    error: current?.error ?? null,
    loading: enabled && current === null,
  };
}
