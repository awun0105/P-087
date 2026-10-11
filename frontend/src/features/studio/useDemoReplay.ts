"use client";

import { useEffect, useRef, useState } from "react";

import type { StageView } from "@/features/studio/PipelineTimeline";
import { STUDIO_STAGES, type StageMeta } from "@/features/studio/stages";
import type { DemoStage } from "@/lib/contracts/studio";

/** Tổng thời gian phát lại; mỗi stage giữ tối thiểu đủ lâu để người xem đọc được. */
const REPLAY_TOTAL_MS = 12000;
const STAGE_MIN_MS = 1400;

/**
 * Phân bổ thời gian phát lại theo tỉ lệ thời lượng thật đã ghi trong bundle.
 * Bundle thiếu thời lượng (smoke) → chia đều; không bịa số giây thật.
 */
export function replayPlan(stages: readonly DemoStage[], stageList: readonly StageMeta[] = STUDIO_STAGES): number[] {
  const recorded = stageList.map((meta) => stages.find((stage) => stage.stage_id === meta.id))
    .filter((stage): stage is DemoStage => !!stage && (stage.state ?? "succeeded") === "succeeded");
  const real = recorded.map((stage) => stage.duration_seconds);
  const known = real.every((value) => value !== null && value > 0);
  const weights = known ? (real as number[]) : real.map(() => 1);
  const sum = weights.reduce((total, value) => total + value, 0);
  const raw = weights.map((weight) => (weight / sum) * REPLAY_TOTAL_MS);
  const lengths = new Map(recorded.map((stage, index) => [stage.stage_id, Math.max(STAGE_MIN_MS, raw[index])]));
  return stageList.map((meta) => lengths.get(meta.id) ?? 0);
}

/** Trạng thái phát lại tại thời điểm `elapsedMs` — hàm thuần để test. */
export function replayState(
  stages: readonly DemoStage[],
  plan: readonly number[],
  elapsedMs: number,
  stageList: readonly StageMeta[] = STUDIO_STAGES,
): StageView[] {
  let cursor = 0;
  return stageList.map((meta, index) => {
    const record = stages.find((stage) => stage.stage_id === meta.id);
    if (!record || (record.state ?? "succeeded") !== "succeeded") {
      return { stage_id: meta.id, state: record?.state === "failed" ? "failed" : "pending", seconds: null, fraction: null };
    }
    const start = cursor;
    const length = plan[index] ?? 0;
    cursor += length;
    const realSeconds = record.duration_seconds;
    if (elapsedMs >= start + length) {
      return { stage_id: meta.id, state: "succeeded", seconds: realSeconds, fraction: 1 };
    }
    if (elapsedMs >= start) {
      return { stage_id: meta.id, state: "running", seconds: null, fraction: (elapsedMs - start) / length };
    }
    return { stage_id: meta.id, state: "pending", seconds: null, fraction: null };
  });
}

/** Chạy phát lại khi `running`; `skip()` nhảy tới cuối. Dọn animation frame khi unmount. */
/** `stageList`: các bước hiển thị (giống tiến trình thật, có thêm bước LiDAR nếu bundle có); mặc định pipeline Studio. */
export function useDemoReplay(stages: readonly DemoStage[], running: boolean, stageList: readonly StageMeta[] = STUDIO_STAGES) {
  const plan = replayPlan(stages, stageList);
  const total = plan.reduce((sum, value) => sum + value, 0);
  const [elapsed, setElapsed] = useState(0);
  const origin = useRef<number | null>(null);

  useEffect(() => {
    if (!running) return;
    let frame = 0;
    const step = (now: number) => {
      if (origin.current === null) origin.current = now;
      const value = Math.min(total, now - origin.current);
      setElapsed(value);
      if (value < total) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [running, total]);

  return {
    views: replayState(stages, plan, elapsed, stageList),
    finished: elapsed >= total,
    skip: () => {
      origin.current = performance.now() - total;
      setElapsed(total);
    },
  };
}
