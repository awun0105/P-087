/** Chọn hộp bằng tia chuột: giao tia với hộp đơn vị trong khung local của hộp. */

import { describe, expect, it } from "vitest";

import { rayTriangles, rayUnitBox } from "@/features/viewer/scene-overlay";

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

describe("rayTriangles", () => {
  // Hình chữ L trong mặt z = 0: hai hình chữ nhật, để lại một góc trống trong hộp bao.
  const positions = [0, 0, 0, 2, 0, 0, 2, 1, 0, 0, 1, 0, 0, 2, 0, 1, 2, 0, 1, 1, 0];
  const indices = [0, 1, 2, 0, 2, 3, 3, 6, 5, 3, 5, 4];

  it("trúng lưới thì trả khoảng cách tới điểm chạm", () => {
    expect(rayTriangles([0.5, 0.5, -4], [0, 0, 1], positions, indices)).toBeCloseTo(4);
    expect(rayTriangles([0.5, 1.5, -2], [0, 0, 1], positions, indices)).toBeCloseTo(2);
  });

  it("bấm vào khoảng trống trong hộp bao không chọn vật", () => {
    expect(rayTriangles([1.5, 1.5, -4], [0, 0, 1], positions, indices)).toBeNull(); // góc khuyết của chữ L
    expect(rayUnitBox([0.25, 0.25, -4], [0, 0, 1])).not.toBeNull(); // hộp thì vẫn trúng
  });

  it("trượt khi tia hướng ra xa, song song mặt, hoặc lưới rỗng", () => {
    expect(rayTriangles([0.5, 0.5, -4], [0, 0, -1], positions, indices)).toBeNull();
    expect(rayTriangles([0.5, 0.5, -4], [1, 0, 0], positions, indices)).toBeNull();
    expect(rayTriangles([0.5, 0.5, -4], [0, 0, 1], [], [])).toBeNull();
  });

  it("lấy tam giác gần nhất và nhận cả hai mặt", () => {
    const stacked = [...positions, 0, 0, 3, 2, 0, 3, 2, 1, 3];
    const order = [...indices, 7, 8, 9];
    expect(rayTriangles([1.5, 0.25, -1], [0, 0, 1], stacked, order)).toBeCloseTo(1);
    expect(rayTriangles([1.5, 0.25, 5], [0, 0, -1], stacked, order)).toBeCloseTo(2);
  });
});
