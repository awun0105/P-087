import { describe, expect, it } from "vitest";

import {
  MAX_BOXES,
  contains,
  toCommandBoxes,
  validateBoxes,
  type EditableBox,
} from "@/features/studio/region/box-model";

const box = (over: Partial<EditableBox> = {}): EditableBox => ({
  id: "b1",
  op: "add",
  center: [0, 0, 0],
  half: [1, 1, 1],
  yaw: 0,
  ...over,
});

describe("contains", () => {
  it("accepts a point inside the box", () => {
    expect(contains(box(), [0.5, -0.5, 0.2])).toBe(true);
  });

  it("accepts points on faces and corners", () => {
    expect(contains(box(), [1, 0, 0])).toBe(true);
    expect(contains(box(), [-1, 1, -1])).toBe(true);
  });

  it("rejects points outside a face with a 1e-6 absolute tolerance", () => {
    expect(contains(box(), [1 + 5e-7, 0, 0])).toBe(true);
    expect(contains(box(), [1 + 2e-6, 0, 0])).toBe(false);
    expect(contains(box(), [0, 0, 1.01])).toBe(false);
  });

  it("tests against the box axes rotated about Z by yaw", () => {
    const rotated = box({ half: [2, 0.5, 0.5], yaw: Math.PI / 2 });
    expect(contains(rotated, [0, 1.5, 0])).toBe(true);
    expect(contains(rotated, [1.5, 0, 0])).toBe(false);
  });

  it("rejects non-finite points", () => {
    expect(contains(box(), [Number.NaN, 0, 0])).toBe(false);
  });
});

describe("toCommandBoxes", () => {
  it("maps to the API wire shape, keeps order and op, and drops id", () => {
    const boxes = [
      box({ center: [1, 2, 3], half: [0.5, 0.6, 0.7], yaw: 0.3 }),
      box({ id: "b2", op: "subtract", center: [0, 0, 0.2], half: [0.25, 0.25, 0.2], yaw: 0 }),
    ];
    expect(toCommandBoxes(boxes)).toEqual([
      { op: "add", center_m: [1, 2, 3], half_extents_m: [0.5, 0.6, 0.7], yaw_rad: 0.3 },
      { op: "subtract", center_m: [0, 0, 0.2], half_extents_m: [0.25, 0.25, 0.2], yaw_rad: 0 },
    ]);
  });

  it("does not share arrays with the input boxes", () => {
    const boxes = [box({ center: [1, 2, 3] })];
    toCommandBoxes(boxes)[0].center_m[0] = 99;
    expect(boxes[0].center).toEqual([1, 2, 3]);
  });
});

describe("validateBoxes", () => {
  it("accepts a valid box set", () => {
    expect(validateBoxes([box()])).toBeNull();
  });

  it("requires at least one add box", () => {
    expect(validateBoxes([])).toBe("Cần ít nhất một box cộng");
    expect(validateBoxes([box({ op: "subtract" })])).toBe("Cần ít nhất một box cộng");
  });

  it("caps the box count at 16", () => {
    const sixteen = Array.from({ length: MAX_BOXES }, (_, i) => box({ id: `b${i}` }));
    expect(validateBoxes(sixteen)).toBeNull();
    expect(validateBoxes([...sixteen, box({ id: "b16" })])).toBe("Tối đa 16 box");
  });

  it("checks half-extents against the closed range [0.005 m, 20 m]", () => {
    expect(validateBoxes([box({ half: [0.005, 0.005, 0.005] })])).toBeNull();
    expect(validateBoxes([box({ half: [20, 20, 20] })])).toBeNull();
    const range = "Box 1: nửa kích thước phải từ 0,005 m đến 20 m";
    expect(validateBoxes([box({ half: [0.004, 1, 1] })])).toBe(range);
    expect(validateBoxes([box({ half: [1, 1, 20.5] })])).toBe(range);
    expect(validateBoxes([box({ half: [1, Number.NaN, 1] })])).toBe(range);
  });

  it("names the 1-based index of the first invalid box", () => {
    expect(validateBoxes([box(), box({ id: "b2", op: "subtract", half: [0, 1, 1] })])).toBe(
      "Box 2: nửa kích thước phải từ 0,005 m đến 20 m",
    );
  });

  it("rejects non-finite centers and yaw", () => {
    expect(validateBoxes([box({ center: [Number.POSITIVE_INFINITY, 0, 0] })])).toBe(
      "Box 1: tọa độ hoặc góc không hợp lệ",
    );
    expect(validateBoxes([box({ yaw: Number.NaN })])).toBe("Box 1: tọa độ hoặc góc không hợp lệ");
  });
});
