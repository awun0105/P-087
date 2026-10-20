import { describe, expect, it } from "vitest";

import { OBJECTIFY_PHASES, geometryPhaseLabel } from "@/lib/scene/geometry-state";

describe("objectify phase labels (T-057)", () => {
  it("has a Vietnamese label for every backend phase", () => {
    for (const phase of OBJECTIFY_PHASES) {
      const label = geometryPhaseLabel(phase);
      expect(label).toBeTruthy();
      expect(label).not.toBe(phase);
    }
  });

  it("returns null when there is no phase", () => {
    expect(geometryPhaseLabel(null)).toBeNull();
  });
});
