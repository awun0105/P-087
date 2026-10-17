"use client";

import { createContext } from "react";

/**
 * Ngữ cảnh đo giá trị của trang scene. Trang scene bật `enabled` khi người xem được sửa job và đang ở tab Studio;
 * các view con (MetricSceneView, kể cả trong tab Kiểm tra) đọc từ đây để gửi phiên Walk. Ngoài trang scene thì
 * giá trị mặc định là tắt, nên không gửi gì.
 */
export interface ValueTracking {
  jobId: string;
  enabled: boolean;
}

export const ValueTrackingContext = createContext<ValueTracking>({ jobId: "", enabled: false });
