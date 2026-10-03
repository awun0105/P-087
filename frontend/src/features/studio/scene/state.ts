import { useEffect, useState } from "react";

import type { JobProgress } from "@/lib/contracts/studio";

/** Kiểu và phép suy trạng thái dùng chung cho các tab của màn scene. */
export type Tab = "progress" | "studio" | "review" | "results";
export type StudioMode = "scene" | "metric" | "gaussian";

export interface SceneInfo {
  name: string;
  videoName: string | null;
  videoSize: number | null;
  /** Tên người tạo scene (không gian chung của nhóm); null khi không biết. */
  createdBy?: string | null;
}

export interface Preview {
  url: string;
  filename: string;
}

export type StageState = "none" | "running" | "succeeded" | "failed";

export function stageState(progress: JobProgress | null, stageId: string): StageState {
  const stage = progress?.stages.find((item) => item.stage_id === stageId);
  if (stage?.state === "running") return "running";
  if (stage?.state === "succeeded") return "succeeded";
  if (stage?.state === "failed") return "failed";
  return "none";
}

export function metricState(progress: JobProgress | null): "waiting" | "confirmed" | "none" {
  if (progress?.waiting_for === "metric_confirmation") return "waiting";
  return stageState(progress, "ST-METRIC-CANONICALIZE") === "succeeded" ? "confirmed" : "none";
}

export function stageSeconds(started: string | null, completed: string | null, now: number | null): number | null {
  if (!started) return null;
  const end = completed ? Date.parse(completed) : now;
  if (end === null) return null;
  return Math.max(0, (end - Date.parse(started)) / 1000);
}

/** Đồng hồ 1 giây cho thời gian đã chạy; tắt khi job không còn chạy. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}
