import { describe, expect, it } from "vitest";

import { guidanceFor } from "@/features/studio/errorGuidance";

describe("guidance for an interrupted worker", () => {
  it("explains a worker shutdown and that retry keeps finished steps", () => {
    const guidance = guidanceFor({
      error_code: "INTERRUPTED_SHUTDOWN",
      stage_id: "ST-CAMERA-POSE",
      human_message: "Worker dừng giữa chừng",
      retryable: true,
    });
    expect(guidance?.cause).toContain("tắt hoặc khởi động lại");
    expect(guidance?.fix).toContain("Thử lại");
  });
});

describe("guidance for a resource wait that ran out (T-050)", () => {
  it("says the wait stopped and to retry after checking the worker", () => {
    const guidance = guidanceFor({ error_code: "RESOURCE_WAIT_EXCEEDED", stage_id: "ST-CAMERA-POSE", human_message: "", retryable: true });
    expect(guidance?.cause).toContain("chờ tài nguyên");
    expect(guidance?.fix).toContain("Thử lại");
  });
});
