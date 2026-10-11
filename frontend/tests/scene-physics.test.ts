// @vitest-environment node
/** Vật lý của scene tương tác chạy bằng chính bản ammo.js phục vụ cho trình duyệt (public/vendor/ammo). */
import { createRequire } from "node:module";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { ScenePhysics, displayToCanonical, nearbyTriangles, sampleHull, type AmmoModule, type PhysicsObjectSpec } from "@/features/viewer/scene-physics";
import type { TriangleMesh } from "@/features/viewer/glb-mesh";
import { fallbackColliderHull, transformColliderHullToObjectFrame } from "@/features/viewer/usePhysicsPlay";

const vendor = path.resolve(__dirname, "../public/vendor/ammo");
let Ammo: AmmoModule;

beforeAll(async () => {
  const factory = createRequire(import.meta.url)(path.join(vendor, "ammo.wasm.js")) as (options: object) => Promise<AmmoModule>;
  Ammo = await factory({ locateFile: (file: string) => path.join(vendor, file) });
});

function crate(overrides: Partial<PhysicsObjectSpec> = {}): PhysicsObjectSpec {
  return {
    id: "crate", position: [0, 0, 0.25], rotation_xyzw: [0, 0, 0, 1], hull: null, dimensions: [0.5, 0.5, 0.5],
    mass_kg: 10, friction: 0.5, restitution: 0, ...overrides,
  };
}

/** Tường phẳng x = `x`, rộng 4 m, cao 2 m (hai tam giác). */
function wall(x: number): TriangleMesh {
  return {
    positions: new Float32Array([x, -2, 0, x, 2, 0, x, 2, 2, x, -2, 2]),
    indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
  };
}

function walk(physics: ScenePhysics, from: number, to: number, seconds: number) {
  const steps = Math.round(seconds * 60);
  let poses = physics.step(1 / 60, [from, 0, 0]);
  for (let i = 1; i <= steps; i += 1) poses = physics.step(1 / 60, [from + ((to - from) * i) / steps, 0, 0]);
  for (let i = 0; i < 60; i += 1) poses = physics.step(1 / 60, null);
  return poses.get("crate")!;
}

describe("vật lý của scene tương tác", () => {
  it("vật đứng yên trên sàn khi không ai chạm vào", () => {
    const physics = new ScenePhysics(Ammo, null, [crate()]);
    const pose = walk(physics, -5, -5, 1);
    expect(pose.position[2]).toBeCloseTo(0.25, 2);
    expect(Math.hypot(pose.position[0], pose.position[1])).toBeLessThan(0.01);
    physics.destroy();
  });

  it("người đi bước vào vật thì đẩy vật đi theo hướng đi", () => {
    const physics = new ScenePhysics(Ammo, null, [crate()]);
    const pose = walk(physics, -2, 1, 2);
    expect(pose.position[0]).toBeGreaterThan(0.8);
    expect(Math.abs(pose.position[1])).toBeLessThan(0.3);
    physics.destroy();
  });

  it("tường của lưới tĩnh chặn vật bị đẩy; đặt lại thì vật về chỗ cũ", () => {
    // Người đi thật bị chính tường chặn (va chạm của viewer) nên dừng trước tường; vật kẹt giữa người và tường.
    const physics = new ScenePhysics(Ammo, wall(1.2), [crate()]);
    const pushed = walk(physics, -2, 0.4, 3);
    expect(pushed.position[0]).toBeGreaterThan(0.6);
    expect(pushed.position[0]).toBeLessThan(1.2 - 0.25 + 0.03);
    physics.reset();
    const back = physics.step(1 / 60, null).get("crate")!;
    expect(back.position[0]).toBeCloseTo(0, 2);
    physics.destroy();
  });

  it("bao lồi từ đỉnh collider dùng được như hộp", () => {
    const corners = [];
    for (const x of [-0.25, 0.25]) for (const y of [-0.25, 0.25]) for (const z of [-0.25, 0.25]) corners.push(x, y, z);
    const physics = new ScenePhysics(Ammo, null, [crate({ hull: new Float32Array(corners), dimensions: null })]);
    expect(walk(physics, -5, -5, 1).position[2]).toBeCloseTo(0.25, 1);
    physics.destroy();
  });
});

describe("dữ liệu cho vật lý", () => {
  it("đổi không gian hiển thị Y-up về hệ canonical Z-up", () => {
    expect(displayToCanonical([1, 2, 3])).toEqual([1, -3, 2]);
  });

  it("đặt đỉnh collider vào khung object trước khi mô phỏng", () => {
    const halfTurn = Math.SQRT1_2;
    const points = transformColliderHullToObjectFrame(new Float32Array([1, 0, 0, -1, 0, 0]), {
      translation_xyz: [2, -1, 0.5],
      rotation_quaternion_xyzw: [0, 0, halfTurn, halfTurn],
    });

    expect(points[0]).toBeCloseTo(2);
    expect(points[1]).toBeCloseTo(0);
    expect(points[2]).toBeCloseTo(0.5);
    expect(points[3]).toBeCloseTo(2);
    expect(points[4]).toBeCloseTo(-2);
    expect(points[5]).toBeCloseTo(0.5);
  });

  it("fallback collider dạng hộp cũng giữ offset của collider con", () => {
    const points = fallbackColliderHull([2, 2, 2], {
      translation_xyz: [2, -1, 0.5],
      rotation_quaternion_xyzw: [0, 0, 0, 1],
    });
    expect(points).not.toBeNull();
    if (!points) throw new Error("expected transformed fallback hull");
    const centroid = [0, 1, 2].map((axis) => {
      let total = 0;
      for (let index = axis; index < points.length; index += 3) total += points[index];
      return total / 8;
    });
    expect(centroid[0]).toBeCloseTo(2);
    expect(centroid[1]).toBeCloseTo(-1);
    expect(centroid[2]).toBeCloseTo(0.5);
  });

  it("lấy mẫu đều khi bao lồi quá nhiều đỉnh", () => {
    const many = new Float32Array(3000 * 3).map((_, i) => i);
    expect(sampleHull(many, 100)).toHaveLength(300);
    expect(sampleHull(new Float32Array(9))).toHaveLength(9);
  });

  it("chỉ giữ lưới tĩnh quanh vật động", () => {
    const mesh: TriangleMesh = {
      positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0, 50, 0, 0, 51, 0, 0, 50, 1, 0]),
      indices: new Uint32Array([0, 1, 2, 3, 4, 5]),
    };
    expect(nearbyTriangles(mesh, [crate()], 6)).toEqual([0]);
  });
});
