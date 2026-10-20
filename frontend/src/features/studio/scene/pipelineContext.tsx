"use client";

import { createContext, useContext } from "react";

import type { PipelineView } from "@/lib/contracts/pipeline";

/** Tiến trình hợp nhất mà trang scene đọc một lần cho cả trang (T-060); null khi chưa có hoặc ngoài trang scene. */
export const PipelineContext = createContext<PipelineView | null>(null);

export function usePipelineView(): PipelineView | null {
  return useContext(PipelineContext);
}
