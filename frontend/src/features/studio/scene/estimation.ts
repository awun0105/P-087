import type { StageView } from "@/features/studio/PipelineTimeline";

/**
 * Benchmark thời gian dự kiến (giây) theo quan sát thực tế trên hệ thống (Quadro T2000, 300-370 frames).
 * - ST-INPUT-VALIDATE: ~5s
 * - ST-PRIVACY-GATE: ~1s
 * - ST-FRAME-EXTRACT: ~25s
 * - ST-CAMERA-POSE: ~1000s (khoảng 16 phút trên CPU 4 threads)
 * - ST-VISUAL-RECON: ~900s (khoảng 15 phút trên GPU Brush 30k iters)
 * - ST-METRIC-CANONICALIZE: user action (không tính vào ETA xử lý của máy)
 * - ST-RGB-GEOMETRY: ~120s (khoảng 2 phút)
 * - ST-OBJECT-EXTRACT: ~360s (khoảng 6 phút SAM2 + inpainting)
 */
export const STAGE_BENCHMARK_SECONDS: Record<string, number> = {
  "ST-INPUT-VALIDATE": 5,
  "ST-PRIVACY-GATE": 1,
  "ST-FRAME-EXTRACT": 25,
  "ST-CAMERA-POSE": 1000,
  "ST-VISUAL-RECON": 900,
  "ST-RGB-GEOMETRY": 120,
  "ST-OBJECT-EXTRACT": 360,
};

export interface PipelineEta {
  /** Thời gian còn lại ước tính của giai đoạn đang chạy (giây) */
  currentStageRemainingSeconds: number | null;
  /** Tổng thời gian còn lại ước tính của các bước máy đang và sẽ tự động xử lý (giây) */
  totalRemainingSeconds: number | null;
  /** Tên định dạng ngắn gọn (vd: "~8 phút 20 giây") */
  formattedRemaining: string | null;
}

/**
 * Tính thời gian còn lại theo thời gian thực (realtime).
 * Khi một stage đang chạy vượt quá thời gian benchmark, ước tính sẽ co giãn mượt mà
 * để không bao giờ hiện số âm hay dừng đếm.
 */
export function estimateRemainingTime(
  stages: readonly StageView[],
  isStale?: boolean,
): PipelineEta {
  const runningStage = stages.find((s) => s.state === "running");
  if (!runningStage || isStale) {
    return {
      currentStageRemainingSeconds: null,
      totalRemainingSeconds: null,
      formattedRemaining: null,
    };
  }

  const currentBenchmark = STAGE_BENCHMARK_SECONDS[runningStage.stage_id] ?? 180;
  const elapsed = runningStage.seconds ?? 0;

  let currentRemaining = 0;
  if (runningStage.fraction !== null && runningStage.fraction > 0 && runningStage.fraction < 1) {
    // Nếu có fraction đo được cụ thể (vd replay hoặc progress)
    currentRemaining = Math.max(5, (elapsed / runningStage.fraction) * (1 - runningStage.fraction));
  } else if (elapsed < currentBenchmark) {
    currentRemaining = currentBenchmark - elapsed;
  } else {
    // Nếu đã chạy lâu hơn benchmark, ước lượng thêm ~10-20% theo thời gian trôi qua
    currentRemaining = Math.max(15, Math.round(currentBenchmark * 0.15));
  }

  // Cộng dồn các bước tự động kế tiếp đang ở trạng thái pending
  let futureRemaining = 0;
  const runningIndex = stages.findIndex((s) => s.stage_id === runningStage.stage_id);
  if (runningIndex >= 0) {
    for (let i = runningIndex + 1; i < stages.length; i++) {
      const futureStage = stages[i];
      if (futureStage.state === "pending") {
        // Bỏ qua các bước tương tác người dùng
        if (futureStage.stage_id === "ST-METRIC-CANONICALIZE") continue;
        futureRemaining += STAGE_BENCHMARK_SECONDS[futureStage.stage_id] ?? 60;
      }
    }
  }

  const totalRemaining = Math.round(currentRemaining + futureRemaining);

  return {
    currentStageRemainingSeconds: Math.round(currentRemaining),
    totalRemainingSeconds: totalRemaining,
    formattedRemaining: formatEtaDuration(totalRemaining),
  };
}

/**
 * Định dạng thời gian ước tính còn lại:
 * Vd: "~45 giây", "~8 phút 30 giây", "~1 giờ 15 phút"
 */
export function formatEtaDuration(seconds: number): string {
  const total = Math.max(5, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;

  if (hours > 0) {
    return `~${hours} giờ ${minutes > 0 ? `${minutes} phút` : ""}`.trim();
  }
  if (minutes > 0) {
    return `~${minutes} phút ${rest > 0 ? `${rest} giây` : ""}`.trim();
  }
  return `~${rest} giây`;
}
