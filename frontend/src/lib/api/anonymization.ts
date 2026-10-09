/** Xem các frame đã che khuôn mặt/biển số và xác nhận trước khi job dựng 3D (AUD-18). */

import { apiFetch } from "@/lib/api/client";

export interface AnonymizationRegion {
  kind: string;
  /** Hộp đã tô (x1, y1, x2, y2) theo pixel của frame. */
  box: [number, number, number, number];
}

export interface AnonymizationFrame {
  frame_name: string;
  width: number;
  height: number;
  regions: AnonymizationRegion[];
}

export interface AnonymizationReview {
  state: "awaiting" | "accepted" | "closed";
  frame_set_checksum: string;
  frame_count: number;
  /** Chỉ gồm frame có vùng bị che. */
  frames: AnonymizationFrame[];
}

const base = (jobId: string) => `/api/v1/jobs/${encodeURIComponent(jobId)}/anonymization`;

export function getAnonymizationReview(jobId: string, signal?: AbortSignal): Promise<AnonymizationReview> {
  return apiFetch<AnonymizationReview>(base(jobId), { signal });
}

export function redactedFrameUrl(jobId: string, frameName: string): string {
  return `${base(jobId)}/frames/${encodeURIComponent(frameName)}`;
}

/** Gửi kèm checksum của bộ frame đã xem: máy chủ từ chối nếu bộ frame đã đổi. */
export function acceptAnonymization(jobId: string, frameSetChecksum: string): Promise<unknown> {
  return apiFetch(`${base(jobId)}/accept`, { method: "POST", body: JSON.stringify({ frame_set_checksum: frameSetChecksum }) });
}
