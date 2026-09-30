/**
 * Hệ trục hiển thị: artifact hệ mét Z-up phải đứng thẳng (sàn nằm ngang) trong viewer Y-up,
 * output COLMAP giữ đúng phép xoay upstream; camera khởi đầu nằm tại camera quay đầu tiên.
 */

import { describe, expect, it } from "vitest";

import { recordingCameraPose, rotate, toDisplay } from "@/features/viewer/source-frame";

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
