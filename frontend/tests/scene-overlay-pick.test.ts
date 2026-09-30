/** Chọn hộp bằng tia chuột: giao tia với hộp đơn vị trong khung local của hộp. */

import { describe, expect, it } from "vitest";

import { rayUnitBox } from "@/features/viewer/scene-overlay";

describe("rayUnitBox", () => {
  it("trúng mặt gần nhất khi tia đi vào hộp", () => {
    expect(rayUnitBox([0, 0, -5], [0, 0, 1])).toBeCloseTo(4.5);
  });

  it("trượt khi tia đi lệch hoặc hướng ra xa", () => {
    expect(rayUnitBox([2, 0, -5], [0, 0, 1])).toBeNull();
    expect(rayUnitBox([0, 0, -5], [0, 0, -1])).toBeNull();
  });

  it("camera nằm trong hộp thì lấy mặt phía trước", () => {
    expect(rayUnitBox([0, 0, 0], [1, 0, 0])).toBeCloseTo(0.5);
  });
});
