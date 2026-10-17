import { describe, expect, it } from "vitest";
import { parseJobProgress } from "@/lib/contracts/studio";

describe("note của tiến trình", () => {
  const progress = (note: unknown) => ({ job_id: "j", status: "SUCCEEDED", preview_ready: true, stages: [{stage_id: "ST-FRAME-EXTRACT", state: "succeeded", note}] });
  it("nhận chuỗi, null và API cũ thiếu note", () => {
    for (const note of ["Chờ bạn duyệt 4 vùng đã che", null, undefined]) expect(parseJobProgress(progress(note)).stages[0].note).toBe(note);
  });
  it("từ chối note không phải chuỗi hoặc null", () => {
    for (const note of [2, false, {}, []]) expect(() => parseJobProgress(progress(note))).toThrow();
  });
});
