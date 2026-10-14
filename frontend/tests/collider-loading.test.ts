import { renderHook, waitFor } from "@testing-library/react";
import type { AppBase } from "playcanvas";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SceneOverlay } from "@/features/viewer/scene-overlay";
import type { PhysicsObjectSpec } from "@/features/viewer/scene-physics";
import type { TriangleMesh } from "@/features/viewer/glb-mesh";
import { usePhysicsPlay, type PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";
import { BOX_POINTS, colliderGlb, type GlbFixtureDocument } from "./helpers/collider-glb";

const constructed = vi.hoisted(() => vi.fn());
vi.mock("@/features/viewer/scene-physics", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/features/viewer/scene-physics")>();
  return {
    ...original,
    loadAmmo: vi.fn().mockResolvedValue({}),
    ScenePhysics: vi.fn(function (_ammo: unknown, environment: TriangleMesh, objects: PhysicsObjectSpec[]) {
      constructed(environment, objects);
      return { destroy: vi.fn(), reset: vi.fn() };
    }),
  };
});

const input: PhysicsObjectInput = {
  id: "asymmetric", position: [10, -20, 30], rotation_xyzw: [0, Math.SQRT1_2, 0, Math.SQRT1_2],
  colliderUrl: "/canonical-object.glb", colliderLocalTransform: null,
  dimensions: [1, 2, 3], mass_kg: 10, friction: 0.5, restitution: 0,
};

function start(object = input) {
  const app = { on: vi.fn(), off: vi.fn() } as unknown as AppBase;
  const overlay = { setObjects: vi.fn() } as unknown as SceneOverlay;
  return renderHook(() => usePhysicsPlay({
    app, overlay,
    walking: true, collisionUrl: "/display-environment.glb", objects: [object], overlayObjects: [],
  }));
}

function stubMeshes(object: ArrayBuffer | number) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const payload = url === "/display-environment.glb" ? colliderGlb({ frame: "display" }) : object;
    return typeof payload === "number"
      ? { ok: false, status: payload }
      : { ok: true, arrayBuffer: async () => payload };
  }));
}

beforeEach(() => constructed.mockClear());
afterEach(() => vi.unstubAllGlobals());

describe("physics mesh frames through the loading hook", () => {
  it("keeps every canonical 1×2×3 collider vertex and converts only the display environment", async () => {
    stubMeshes(colliderGlb());
    const { result } = start();
    await waitFor(() => expect(result.current.status.state).toBe("ready"));
    const [environment, objects] = constructed.mock.calls[0] as [TriangleMesh, PhysicsObjectSpec[]];
    expect(Array.from(environment.positions)).toEqual(BOX_POINTS.flat());
    expect(Array.from(objects[0].hull!)).toEqual(BOX_POINTS.flat());
    expect(objects[0].position).toEqual(input.position);
    expect(objects[0].rotation_xyzw).toEqual(input.rotation_xyzw);
  });

  it("applies the rotated/off-center child collider once to a supported single part", async () => {
    stubMeshes(colliderGlb());
    const { result } = start({ ...input, colliderLocalTransform: {
      translation_xyz: [2, -1, 0.5], rotation_quaternion_xyzw: [0, 0, Math.SQRT1_2, Math.SQRT1_2],
    } });
    await waitFor(() => expect(result.current.status.state).toBe("ready"));
    const [, objects] = constructed.mock.calls[0] as [TriangleMesh, PhysicsObjectSpec[]];
    const expected = BOX_POINTS.flatMap(([x, y, z]) => [2 - y, -1 + x, 0.5 + z]);
    Array.from(objects[0].hull!).forEach((value, index) => expect(value).toBeCloseTo(expected[index], 5));
    expect(objects[0].position).toEqual(input.position);
    expect(objects[0].rotation_xyzw).toEqual(input.rotation_xyzw);
  });

  it.each<[string, (document: GlbFixtureDocument) => void]>([
    ["node transform", (document) => { document.nodes[1].matrix![12] = 5; }],
    ["sparse accessor", (document) => { document.accessors[0].sparse = { count: 1 }; }],
  ])("reports unsupported %s instead of quietly using a fallback box", async (_name, edit) => {
    stubMeshes(colliderGlb({ edit }));
    const { result } = start();
    await waitFor(() => expect(result.current.status.state).toBe("failed"));
    expect(result.current.status).toMatchObject({ state: "failed", message: expect.stringMatching(/asymmetric: GLB/) });
    expect(constructed).not.toHaveBeenCalled();
  });

  it("blocks unavailable collider bytes instead of replacing geometry with a box", async () => {
    stubMeshes(404);
    const { result } = start();
    await waitFor(() => expect(result.current.status.state).toBe("failed"));
    expect(constructed).not.toHaveBeenCalled();
  });

  it("reports multipart rather than building a convex hull across all parts", async () => {
    const other = BOX_POINTS.map(([x, y, z]) => [x + 4, y, z] as [number, number, number]);
    stubMeshes(colliderGlb({ parts: [BOX_POINTS, other] }));
    const { result } = start();
    await waitFor(() => expect(result.current.status).toMatchObject({ state: "failed", message: expect.stringContaining("BLOCKED BY PR-04") }));
    expect(constructed).not.toHaveBeenCalled();
  });

  it.each([
    { dynamic: false }, { colliderType: "CONVEX_DECOMPOSITION" }, { colliderType: "SIMPLIFIED_MESH" },
  ])("explicitly blocks unsupported physics %j", async (flags) => {
    stubMeshes(colliderGlb());
    const { result } = start({ ...input, ...flags });
    await waitFor(() => expect(result.current.status).toMatchObject({ state: "failed", message: expect.stringContaining("BLOCKED BY PR-04") }));
    expect(constructed).not.toHaveBeenCalled();
  });
});
