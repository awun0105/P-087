import { describe, expect, it } from "vitest";

import { STAGE_IDS } from "@/lib/contracts/api";

describe("StageId mirrors the backend enum (T-056)", () => {
  it("includes the anonymization review step right after frame extraction", () => {
    const frame = STAGE_IDS.indexOf("ST-FRAME-EXTRACT");
    expect(STAGE_IDS[frame + 1]).toBe("ST-ANONYMIZATION-REVIEW");
  });
});
