import { describe, expect, it } from "vitest";

import { buildOccupancy, gaitForSpeed, occupancyTest, thirdPersonCameraPosition, type ThirdPersonOptions } from "@/features/viewer/third-person";

const OPTIONS: ThirdPersonOptions = { distance: 2, lift: 0.4, margin: 0.2, step: 0.1 };

describe("camera góc nhìn thứ ba", () => {
  it("lùi sau lưng theo hướng nhìn ngang và nâng lên", () => {
    // Nhìn về −Z (hướng mặc định của camera) và hơi cúi: phần cúi không kéo camera xuống đất.
    const position = thirdPersonCameraPosition([1, 1.3, 5], [0, -0.5, -1], OPTIONS);
    expect(position[0]).toBeCloseTo(1);
    expect(position[1]).toBeCloseTo(1.7);
    expect(position[2]).toBeCloseTo(7);
  });

  it("dừng trước tường ở sau lưng thay vì lùi xuyên qua", () => {
    const wall = (point: [number, number, number]) => point[2] >= 6;
    const position = thirdPersonCameraPosition([1, 1.3, 5], [0, 0, -1], OPTIONS, wall);
    expect(position[2]).toBeGreaterThan(5);
    expect(position[2]).toBeLessThan(6 - OPTIONS.margin + 1e-6);
  });

  it("đứng sát tường thì camera ở ngay tầm mắt", () => {
    const position = thirdPersonCameraPosition([0, 1.3, 0], [1, 0, 0], OPTIONS, () => true);
    expect(position).toEqual([0, 1.3, 0]);
  });

  it("nhìn thẳng xuống thì chỉ nâng camera, không chọn bừa một hướng lùi", () => {
    const position = thirdPersonCameraPosition([2, 1.3, 2], [0, -1, 0], OPTIONS);
    expect(position[0]).toBe(2);
    expect(position[1]).toBeCloseTo(1.7);
    expect(position[2]).toBe(2);
  });

  it("lưới va chạm thành tập ô tra được theo toạ độ", () => {
    const occupied = occupancyTest(buildOccupancy([0.01, 0.01, 0.01, 1.0, 2.0, 3.0], 0.15), 0.15);
    expect(occupied([0.1, 0.1, 0.1])).toBe(true);
    expect(occupied([1.02, 2.05, 3.1])).toBe(true);
    expect(occupied([0.4, 0.1, 0.1])).toBe(false);
  });

  it("dáng đi theo tốc độ: đứng yên, đi bộ, chạy", () => {
    expect(gaitForSpeed(0)).toBe("idle");
    expect(gaitForSpeed(Number.NaN)).toBe("idle");
    expect(gaitForSpeed(1.4)).toBe("walk");
    expect(gaitForSpeed(4)).toBe("run");
  });
});
