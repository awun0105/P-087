import { describe, expect, it } from "vitest";
import { guidanceFor } from "@/features/studio/errorGuidance";
import type { ExecutionError } from "@/lib/contracts/api";

function error(code: string): ExecutionError {
  return { stage_id: "ST-CAMERA-POSE", error_code: code, human_message: "", retryable: true, details: null } as ExecutionError;
}

describe("error guidance for the time-limit and GPU budget codes (T-043)", () => {
  it("explains a stalled tool and says to retry", () => {
    const guidance = guidanceFor(error("PROCESS_STALLED"));
    expect(guidance?.cause).toContain("không ghi tiến triển");
    expect(guidance?.fix).toContain("Thử lại");
  });

  it("explains a LiDAR odometry stall the same way", () => {
    const guidance = guidanceFor(error("LIDAR_ODOMETRY_STALLED"));
    expect(guidance?.cause).toContain("không tiến triển");
    expect(guidance?.fix).toContain("Thử lại");
  });

  it("explains a run slower than the expected deadline and offers a retry or a smaller input", () => {
    const guidance = guidanceFor(error("EXPECTED_DURATION_EXCEEDED"));
    expect(guidance?.cause).toContain("thời gian thường thấy");
    expect(guidance?.fix).toContain("Số khung hình tối đa");
  });

  it("explains the GPU hour cap and names the setting the operator must raise", () => {
    const guidance = guidanceFor(error("GPU_BUDGET_EXCEEDED"));
    expect(guidance?.cause).toContain("giờ GPU");
    expect(guidance?.fix).toContain("PRODUCT_JOB_GPU_HOURS_MAX");
  });

  it("keeps returning null for codes without specific guidance", () => {
    expect(guidanceFor(error("SOMETHING_ELSE"))).toBeNull();
  });
});
