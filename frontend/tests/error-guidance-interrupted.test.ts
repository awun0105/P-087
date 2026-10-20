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

describe("guidance for pipeline-view step errors (T-061)", () => {
  it("explains object extraction that needs a choice", () => {
    const guidance = guidanceFor({ error_code: "OBJECTIFY_AWAITING_CHOICE", stage_id: "ST-OBJECT-EXTRACT", human_message: "", retryable: true });
    expect(guidance?.fix).toContain("hộp ứng viên");
  });
  it("explains a failed mesh build", () => {
    const guidance = guidanceFor({ error_code: "OBJECT_GEOMETRY_BUILD_FAILED", stage_id: "ST-SCENE-DECOMPOSE", human_message: "", retryable: true });
    expect(guidance?.fix).toContain("Tạo mesh");
  });
});
