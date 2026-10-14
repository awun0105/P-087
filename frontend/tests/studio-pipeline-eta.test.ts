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

  it("không ước lượng từ benchmark tĩnh khi stage không có fraction đo được", () => {
    const stages: StageView[] = [
      { stage_id: "ST-FRAME-EXTRACT", state: "running", seconds: 35, fraction: null },
      { stage_id: "ST-CAMERA-POSE", state: "pending", seconds: null, fraction: null },
    ];
    const eta = estimateRemainingTime(stages);
    expect(eta.currentStageRemainingSeconds).toBeNull();
    expect(eta.totalRemainingSeconds).toBeNull();
    expect(eta.formattedRemaining).toBeNull();
  });

  it("chỉ ước lượng stage hiện tại từ elapsed time và fraction đo được", () => {
    const stages: StageView[] = [
      { stage_id: "ST-FRAME-EXTRACT", state: "running", seconds: 40, fraction: 0.5 },
      { stage_id: "ST-CAMERA-POSE", state: "pending", seconds: null, fraction: null },
    ];
    const eta = estimateRemainingTime(stages);
    expect(eta.currentStageRemainingSeconds).toBe(40);
    expect(eta.totalRemainingSeconds).toBeNull();
    expect(eta.formattedRemaining).toBeNull();
  });

  it("chỉ hiển thị tổng ETA khi không còn stage tương lai chưa hoàn tất", () => {
    const stages: StageView[] = [
      { stage_id: "ST-FRAME-EXTRACT", state: "running", seconds: 40, fraction: 0.5 },
      { stage_id: "ST-CAMERA-POSE", state: "succeeded", seconds: 120, fraction: 1 },
    ];
    const eta = estimateRemainingTime(stages);
    expect(eta.currentStageRemainingSeconds).toBe(40);
    expect(eta.totalRemainingSeconds).toBe(40);
    expect(eta.formattedRemaining).toBe("~40 giây");
  });

  it("format thời lượng ngắn gọn theo phút và giây", () => {
    expect(formatEtaDuration(1)).toBe("~1 giây");
    expect(formatEtaDuration(45)).toBe("~45 giây");
    expect(formatEtaDuration(125)).toBe("~2 phút 5 giây");
    expect(formatEtaDuration(3665)).toBe("~1 giờ 1 phút");
  });
});
