import { describe, expect, it } from "vitest";

import {
  MAX_BOXES,
  MAX_HALF_M,
  MIN_HALF_M,
  contains,
  dragFace,
  faceCenter,
  faceNormal,
  rotateYaw,
  toCommandBoxes,
  translateBox,
  validateBoxes,
  type EditableBox,
  type Vec3,
} from "@/features/studio/region/box-model";

const box = (over: Partial<EditableBox> = {}): EditableBox => ({
  id: "b1",
  op: "add",
  center: [0, 0, 0],
  half: [1, 1, 1],
  yaw: 0,
  ...over,
});

// Compares numerically, so -0 and +0 from sign flips are equal here.
const expectVec3Close = (actual: Vec3, expected: Vec3) => {
  actual.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 9));
};

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

describe("dragFace", () => {
  it("grows +x by the drag amount and keeps the -x face fixed at yaw 0", () => {
    const out = dragFace(box({ half: [0.5, 0.5, 0.5] }), "+x", 0.1);
    expect(out.half[0]).toBeCloseTo(0.55, 9);
    expect(out.center[0]).toBeCloseTo(0.05, 9);
    expect(out.center[1]).toBeCloseTo(0, 9);
    expect(out.center[0] - out.half[0]).toBeCloseTo(-0.5, 9);
  });

  it("moves along world +y at yaw π/2 and keeps the opposite face fixed", () => {
    const base = box({ half: [0.5, 0.5, 0.5], yaw: Math.PI / 2 });
    const out = dragFace(base, "+x", 0.1);
    expect(out.half[0]).toBeCloseTo(0.55, 9);
    expect(out.center[0]).toBeCloseTo(0, 9);
    expect(out.center[1]).toBeCloseTo(0.05, 9);
    expectVec3Close(faceCenter(out, "-x"), faceCenter(base, "-x"));
  });

  it("clamps a shrinking drag at MIN_HALF_M without flipping the box", () => {
    const out = dragFace(box({ half: [0.5, 0.5, 0.5] }), "+x", -5);
    expect(out.half[0]).toBe(MIN_HALF_M);
    expect(out.center[0] - out.half[0]).toBeCloseTo(-0.5, 9);
    expect(out.center[0] + out.half[0]).toBeCloseTo(-0.49, 9);
  });

  it("clamps growth at MAX_HALF_M", () => {
    expect(dragFace(box(), "+x", 100).half[0]).toBe(MAX_HALF_M);
  });

  it("drags the -x face toward -x and keeps +x fixed", () => {
    const out = dragFace(box({ half: [0.5, 0.5, 0.5] }), "-x", 0.2);
    expect(out.half[0]).toBeCloseTo(0.6, 9);
    expect(out.center[0]).toBeCloseTo(-0.1, 9);
    expect(out.center[0] + out.half[0]).toBeCloseTo(0.5, 9);
  });

  it("moves z faces along world Z regardless of yaw", () => {
    const out = dragFace(box({ half: [0.5, 0.5, 0.5], yaw: 1.2 }), "+z", 0.2);
    expect(out.half[2]).toBeCloseTo(0.6, 9);
    expect(out.center[2]).toBeCloseTo(0.1, 9);
    expect(out.center[0]).toBeCloseTo(0, 9);
    expect(out.center[1]).toBeCloseTo(0, 9);
  });

  it("returns a new box and does not mutate the input", () => {
    const base = box({ half: [0.5, 0.5, 0.5] });
    dragFace(base, "+x", 0.1);
    expect(base.half).toEqual([0.5, 0.5, 0.5]);
    expect(base.center).toEqual([0, 0, 0]);
  });
});

describe("translateBox", () => {
  it("moves the centre and keeps size and yaw", () => {
    const out = translateBox(box({ center: [1, 2, 3], half: [0.5, 0.5, 0.5], yaw: 0.4 }), [-1, 0.5, 2]);
    expect(out.center).toEqual([0, 2.5, 5]);
    expect(out.half).toEqual([0.5, 0.5, 0.5]);
    expect(out.yaw).toBe(0.4);
  });
});

describe("rotateYaw", () => {
  it("adds the delta and wraps the result into (-π, π]", () => {
    expect(rotateYaw(box(), Math.PI / 2).yaw).toBeCloseTo(Math.PI / 2, 12);
    expect(rotateYaw(box({ yaw: 0.75 * Math.PI }), Math.PI / 2).yaw).toBeCloseTo(-0.75 * Math.PI, 12);
    expect(rotateYaw(box(), 2 * Math.PI).yaw).toBeCloseTo(0, 12);
  });

  it("keeps π as π rather than -π", () => {
    expect(rotateYaw(box({ yaw: Math.PI }), 0).yaw).toBe(Math.PI);
  });
});

describe("faceCenter and faceNormal", () => {
  it("returns face centres and outward normals in object-local space at yaw 0", () => {
    const b = box({ center: [1, 0, 0], half: [2, 1, 3] });
    expectVec3Close(faceCenter(b, "+x"), [3, 0, 0]);
    expectVec3Close(faceCenter(b, "-y"), [1, -1, 0]);
    expectVec3Close(faceNormal(b, "-y"), [0, -1, 0]);
  });

  it("follows yaw for x and y faces and leaves z faces on world Z", () => {
    const b = box({ half: [2, 1, 3], yaw: Math.PI / 2 });
    expectVec3Close(faceCenter(b, "+x"), [0, 2, 0]);
    expectVec3Close(faceNormal(b, "+x"), [0, 1, 0]);
    expectVec3Close(faceNormal(b, "+y"), [-1, 0, 0]);
    expectVec3Close(faceCenter(b, "+z"), [0, 0, 3]);
  });
});
