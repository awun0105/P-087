import { describe, expect, it } from "vitest";
import { estimateRemainingTime, formatEtaDuration } from "@/features/studio/scene/estimation";
import type { StageView } from "@/features/studio/PipelineTimeline";

describe("ước lượng thời gian xử lý realtime", () => {
  it("trả về null khi không có stage nào đang chạy", () => {
    const stages: StageView[] = [
      { stage_id: "ST-INPUT-VALIDATE", state: "succeeded", seconds: 5, fraction: 1 },
      { stage_id: "ST-PRIVACY-GATE", state: "succeeded", seconds: 1, fraction: 1 },
      { stage_id: "ST-FRAME-EXTRACT", state: "pending", seconds: null, fraction: null },
    ];
    const eta = estimateRemainingTime(stages);
    expect(eta.currentStageRemainingSeconds).toBeNull();
    expect(eta.totalRemainingSeconds).toBeNull();
    expect(eta.formattedRemaining).toBeNull();
  });

  it("tính thời gian còn lại của stage và các stage pending kế tiếp", () => {
    const stages: StageView[] = [
      { stage_id: "ST-INPUT-VALIDATE", state: "succeeded", seconds: 5, fraction: 1 },
      { stage_id: "ST-PRIVACY-GATE", state: "succeeded", seconds: 1, fraction: 1 },
      { stage_id: "ST-FRAME-EXTRACT", state: "running", seconds: 15, fraction: null }, // benchmark 25s -> còn 10s
      { stage_id: "ST-CAMERA-POSE", state: "pending", seconds: null, fraction: null }, // benchmark 1000s
    ];
    const eta = estimateRemainingTime(stages);
    expect(eta.currentStageRemainingSeconds).toBe(10);
    expect(eta.totalRemainingSeconds).toBe(1010);
    expect(eta.formattedRemaining).toContain("16 phút");
  });

  it("co giãn mượt mà khi chạy quá thời gian benchmark mà không bị âm", () => {
    const stages: StageView[] = [
      { stage_id: "ST-FRAME-EXTRACT", state: "running", seconds: 35, fraction: null }, // benchmark 25s, đã chạy 35s
    ];
    const eta = estimateRemainingTime(stages);
    expect(eta.currentStageRemainingSeconds).toBeGreaterThan(0);
    expect(eta.totalRemainingSeconds).toBeGreaterThan(0);
  });

  it("format thời lượng ngắn gọn theo phút và giây", () => {
    expect(formatEtaDuration(45)).toBe("~45 giây");
    expect(formatEtaDuration(125)).toBe("~2 phút 5 giây");
    expect(formatEtaDuration(3665)).toBe("~1 giờ 1 phút");
  });
});
