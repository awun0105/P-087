import { describe, expect, it } from "vitest";

import { viewerRenderer } from "@/features/viewer/renderer-setting";

describe("viewer renderer setting (T-065)", () => {
  it("defaults to webgl", () => {
    expect(viewerRenderer(undefined, true)).toBe("webgl");
    expect(viewerRenderer("webgl", true)).toBe("webgl");
    expect(viewerRenderer("nonsense", true)).toBe("webgl");
  });
  it("auto uses WebGPU only when the browser has it", () => {
    expect(viewerRenderer("auto", true)).toBe("webgpu");
    expect(viewerRenderer("auto", false)).toBe("webgl");
  });
});
