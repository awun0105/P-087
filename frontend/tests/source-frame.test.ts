/**
 * Hệ trục hiển thị: artifact hệ mét Z-up phải đứng thẳng (sàn nằm ngang) trong viewer Y-up,
 * output COLMAP giữ đúng phép xoay upstream; camera khởi đầu nằm tại camera quay đầu tiên.
 */

import { describe, expect, it } from "vitest";

import { interiorFallbackPose, objectViewPose, recordingCameraPose, rotate, toDisplay } from "@/features/viewer/source-frame";

/** Bỏ −0 để so bằng giá trị. */
const clean = (v: number[]) => v.map((x) => x + 0);

describe("source frame", () => {
  it("Z-up hệ mét: trục lên z thành y của viewer, không soi gương", () => {
    expect(clean(toDisplay("z_up", [0, 0, 1]))).toEqual([0, 1, 0]);
    expect(clean(toDisplay("z_up", [1, 0, 0]))).toEqual([1, 0, 0]);
    expect(clean(toDisplay("z_up", [0, 1, 0]))).toEqual([0, 0, -1]);
    const [a, b] = [toDisplay("z_up", [1, 0, 0]), toDisplay("z_up", [0, 1, 0])];
    const cross = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    expect(clean(cross)).toEqual(clean(toDisplay("z_up", [0, 0, 1]))); // x × y = z vẫn đúng sau đổi hệ
  });

  it("COLMAP: y xuống thành y lên (phép xoay 180° quanh Z của upstream)", () => {
    expect(clean(toDisplay("colmap", [0, -1, 0]))).toEqual([0, 1, 0]);
  });

  it("camera khởi đầu tại camera quay đầu, nhìn theo trục z của nó", () => {
    // Camera OpenCV nhìn theo +x của world Z-up: R đưa z_cam → x_world, y_cam(xuống) → −z_world.
    const lookX: [number, number, number, number] = [0.5, -0.5, 0.5, -0.5];
    expect(rotate(lookX, [0, 0, 1]).map((v) => Math.round(v * 1e6) / 1e6)).toEqual([1, 0, 0]);
    expect(rotate(lookX, [0, -1, 0]).map((v) => Math.round(v * 1e6) / 1e6)).toEqual([0, 0, 1]);
    const pose = recordingCameraPose("z_up", [
      { center: [2, 3, 0.4], rotation_xyzw: lookX },
      { center: [12, 3, 0.4], rotation_xyzw: lookX },
    ])!;
    expect(pose.position).toEqual([2, 0.4, -3]);
    expect(pose.target[0]).toBeCloseTo(5.5); // 35% của quỹ đạo 10 m phía trước
    expect(pose.target[1]).toBeCloseTo(0.4); // cùng độ cao: nhìn ngang, không cắm xuống sàn
  });

  it("không có camera thì để viewer dùng mặc định", () => {
    expect(recordingCameraPose("colmap", [])).toBeUndefined();
  });
});

describe("objectViewPose", () => {
  // Camera nhìn theo +x của world (xem test camera khởi đầu).
  const lookX: [number, number, number, number] = [0.5, -0.5, 0.5, -0.5];

  it("đứng tại camera quay gần nhất đã nhìn thấy vật", () => {
    const cameras = [
      { center: [0, 0, 0.4] as [number, number, number], rotation_xyzw: lookX },
      { center: [3, 0, 0.4] as [number, number, number], rotation_xyzw: lookX },
    ];
    const pose = objectViewPose([6, 0, 0.3], [1, 1, 0.6], cameras);
    expect(pose.position).toEqual(toDisplay("z_up", [3, 0, 0.4])); // gần hơn và vật ở phía trước
    expect(pose.target).toEqual(toDisplay("z_up", [6, 0, 0.3]));
  });

  it("không camera nào thấy vật thì lùi ra và nâng lên", () => {
    const behind = [{ center: [10, 0, 0.4] as [number, number, number], rotation_xyzw: lookX }];
    const pose = objectViewPose([6, 0, 0.3], [1, 1, 0.6], behind);
    expect(pose.position[1]).toBeGreaterThan(0.3); // cao hơn tâm vật (trục y hiển thị = z canonical)
  });
});

describe("interiorFallbackPose", () => {
  it("định vị camera bên trong hộp không gian hệ z_up tại tầm mắt và nhìn dọc trục dài", () => {
    const box = { min: [0, 0, 0] as [number, number, number], max: [20, 10, 3] as [number, number, number] };
    const pose = interiorFallbackPose("z_up", box);
    // position Y trong viewer là Z canonical (độ cao): 1.5m
    expect(pose.position[1]).toBeCloseTo(1.5);
    // Target nhìn dọc theo trục X (dài 20m > 10m)
    expect(pose.target[0]).toBeGreaterThan(pose.position[0]);
  });

  it("định vị camera bên trong hộp không gian hệ colmap", () => {
    const box = { min: [-5, -2, 0] as [number, number, number], max: [5, 2, 15] as [number, number, number] };
    const pose = interiorFallbackPose("colmap", box);
    expect(pose.position).toBeDefined();
    expect(pose.target).toBeDefined();
    expect(pose.fov).toBe(60);
  });
});
