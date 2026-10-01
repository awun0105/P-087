"use client";

import WebViewer from "@rerun-io/web-viewer-react";
import { useSyncExternalStore } from "react";

import { trainingRecordingUrl } from "@/lib/api/studio";

const noSubscribe = () => () => {};

/**
 * Chế độ xem thứ hai, tuỳ chọn, của bước 3DGS: phát lại quá trình train do Brush ghi ra Rerun (camera COLMAP, ảnh
 * render ↔ ảnh thật ở từng mốc đánh giá, PSNR/SSIM, loss, đám Gaussian theo thời gian). Chỉ đọc; không thay viewer
 * 3DGS và không ghi gì vào scene. Viewer Rerun phải cùng phiên bản với SDK mà Brush nhúng (0.24.1) — đổi phiên bản
 * Brush thì đổi gói `@rerun-io/web-viewer-react` theo. Component của Rerun tự huỷ canvas/WASM khi unmount.
 */
export function RerunTrainingView({ jobId }: { jobId: string }) {
  // Viewer Rerun cần URL tuyệt đối; origin chỉ có ở trình duyệt.
  const origin = useSyncExternalStore(noSubscribe, () => window.location.origin, () => null);
  if (!origin) return null;
  return (
    <div className="absolute inset-0 bg-viewport">
      <WebViewer rrd={`${origin}${trainingRecordingUrl(jobId)}`} width="100%" height="100%" hide_welcome_screen />
    </div>
  );
}
