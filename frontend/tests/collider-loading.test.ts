import { renderHook, waitFor } from "@testing-library/react";
import type { AppBase } from "playcanvas";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SceneOverlay } from "@/features/viewer/scene-overlay";
import type { PhysicsObjectSpec } from "@/features/viewer/scene-physics";
import type { TriangleMesh } from "@/features/viewer/glb-mesh";
import { usePhysicsPlay, type PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";
import { BOX_POINTS, colliderGlb, type GlbFixtureDocument } from "./helpers/collider-glb";

const constructed = vi.hoisted(() => vi.fn());
const destructed = vi.hoisted(() => vi.fn());
vi.mock("@/features/viewer/scene-physics", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/features/viewer/scene-physics")>();
  return {
    ...original,
    loadAmmo: vi.fn().mockResolvedValue({}),
    ScenePhysics: vi.fn(function (_ammo: unknown, environment: TriangleMesh, objects: PhysicsObjectSpec[]) {
      constructed(environment, objects);
      return { destroy: destructed, reset: vi.fn() };
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

beforeEach(() => { constructed.mockClear(); destructed.mockClear(); });
afterEach(() => vi.unstubAllGlobals());

describe("physics mesh frames through the loading hook", () => {
  it("keeps every canonical 1×2×3 collider vertex and converts only the display environment", async () => {
    stubMeshes(colliderGlb());
    const { result } = start();
    await waitFor(() => expect(result.current.status.state).toBe("ready"));
    const [environment, objects] = constructed.mock.calls[0] as [TriangleMesh, PhysicsObjectSpec[]];
    expect(Array.from(environment.positions)).toEqual(BOX_POINTS.flat());
    expect(Array.from(objects[0].parts![0].positions)).toEqual(BOX_POINTS.flat());
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
    const expected = BOX_POINTS.flat();
    expect(objects[0].colliderLocalTransform?.translation_xyz).toEqual([2,-1,.5]);
    expect(objects[0].colliderLocalTransform?.rotation_quaternion_xyzw).toEqual([0,0,Math.SQRT1_2,Math.SQRT1_2]);
    Array.from(objects[0].parts![0].positions).forEach((value, index) => expect(value).toBeCloseTo(expected[index], 5));
    expect(objects[0].position).toEqual(input.position);
    expect(objects[0].rotation_xyzw).toEqual(input.rotation_xyzw);
  });

  it.each<[string, (document: GlbFixtureDocument) => void]>([
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
    await waitFor(() => expect(result.current.status).toMatchObject({ state: "failed", message: expect.stringContaining("CONVEX_HULL requires exactly one part") }));
    expect(constructed).not.toHaveBeenCalled();
  });

  it.each([
    { dynamic: false }, { colliderType: "CONVEX_DECOMPOSITION" }, { colliderType: "SIMPLIFIED_MESH", dynamic: false },
  ])("loads supported static/multipart physics %j", async (flags) => {
    stubMeshes(colliderGlb());
    const { result } = start({ ...input, ...flags });
    await waitFor(() => expect(result.current.status.state).toBe("ready"));
    expect(constructed).toHaveBeenCalledOnce();
    if (flags.dynamic === false) expect(constructed.mock.calls[0][1][0].mass_kg).toBe(0);
  });

  it.each([
    { colliderType: "SIMPLIFIED_MESH", mass_kg: 10 }, { colliderType: "CONVEX_HULL", mass_kg: null },
  ])("blocks unsafe/missing dynamic input %j", async (flags) => {
    stubMeshes(colliderGlb());
    const { result } = start({ ...input, ...flags });
    await waitFor(() => expect(result.current.status.state).toBe("failed"));
    expect(constructed).not.toHaveBeenCalled();
  });
});

it("prepares camera before Walk, preserves physics for viewport hide, rebuilds moved poses, and releases on Exit/Delete/Restore", async()=>{
  stubMeshes(colliderGlb());
  const callbacks=new Map<string,(dt:number)=>void>();
  const app={on:vi.fn((event:string,fn:(dt:number)=>void)=>callbacks.set(event,fn)),off:vi.fn((event:string)=>callbacks.delete(event))} as unknown as AppBase;
  const overlay={setObjects:vi.fn()} as unknown as SceneOverlay;
  const sink=vi.fn();
  const {result,rerender,unmount}=renderHook(({walking,objects,visible})=>usePhysicsPlay({app,overlay,walking,collisionUrl:"/display-environment.glb",objects,overlayObjects:[{id:input.id,url:"/object.ply",position:input.position,rotation_xyzw:input.rotation_xyzw,visible}],onObjectCollision:sink}),{initialProps:{walking:false,objects:[input],visible:true}});
  await waitFor(()=>expect(result.current.status.state).toBe("ready"));
  expect(constructed).not.toHaveBeenCalled();expect(sink.mock.lastCall![0]).not.toBeNull();
  rerender({walking:true,objects:[input],visible:true});await waitFor(()=>expect(constructed).toHaveBeenCalledTimes(1));
  rerender({walking:true,objects:[input],visible:false});expect(constructed).toHaveBeenCalledTimes(1);
  const moved={...input,position:[30,40,5] as [number,number,number]};
  rerender({walking:true,objects:[moved],visible:false});
  await waitFor(()=>expect(constructed).toHaveBeenCalledTimes(2));expect(constructed.mock.lastCall![1][0].position).toEqual(moved.position);
  expect(vi.mocked(fetch).mock.calls.filter(([url])=>url==="/canonical-object.glb")).toHaveLength(1); // Pose edit reuses parsed collider bytes.
  rerender({walking:false,objects:[moved],visible:false});expect(callbacks.size).toBe(0);
  rerender({walking:false,objects:[],visible:false});expect(result.current.status.state).toBe("off");expect(sink.mock.lastCall![0]).toBeNull();
  rerender({walking:true,objects:[moved],visible:true});await waitFor(()=>expect(constructed).toHaveBeenCalledTimes(3));
  unmount();expect(callbacks.size).toBe(0);expect(destructed).toHaveBeenCalledTimes(3);
});

it("an old collider response cannot resurrect an object deleted before loading finishes", async()=>{
  let complete: ((response:object)=>void)|undefined;
  vi.stubGlobal("fetch",vi.fn((url:string)=>url==="/canonical-object.glb"?new Promise(resolve=>{complete=resolve;}):Promise.resolve({ok:true,arrayBuffer:async()=>colliderGlb({frame:"display"})})));
  const app={on:vi.fn(),off:vi.fn()} as unknown as AppBase;
  const overlay={setObjects:vi.fn()} as unknown as SceneOverlay;
  const {result,rerender}=renderHook(({objects})=>usePhysicsPlay({app,overlay,walking:true,collisionUrl:"/display-environment.glb",objects,overlayObjects:[]}),{initialProps:{objects:[input]}});
  await waitFor(()=>expect(complete).toBeDefined());
  rerender({objects:[]});
  complete!({ok:true,arrayBuffer:async()=>colliderGlb()});
  await waitFor(()=>expect(result.current.status.state).toBe("off"));
  expect(constructed).not.toHaveBeenCalled();
});
