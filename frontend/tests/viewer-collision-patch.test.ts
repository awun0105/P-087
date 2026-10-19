// @vitest-environment node
/** Execute the installed viewer's patched callbacks; graphics are stubbed, not a browser acceptance test. */
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, it, vi } from "vitest";

it("the installed bridge updates camera/input/navigation and releases overlays without listener accumulation", () => {
  const source = readFileSync(new URL("../node_modules/@playcanvas/supersplat-viewer/dist/viewer.js", import.meta.url), "utf8");
  const init = source.slice(source.indexOf("let collisionReady = null;"), source.indexOf("collisionLoad?.then"));
  const attach = source.slice(source.indexOf("attachCollision = (collision) => {"), source.indexOf("// collision may already have landed"));
  expect(init).toContain("REAL2SIM_HOST_COLLISION");
  class MeshCollision { constructor(public positions: Float32Array, public indices: Uint32Array) {} }
  class MeshDebugOverlay { destroy = vi.fn(); enabled = false; }
  const listeners = new Set<unknown>();
  const events = {
    on: (_name: string, fn: unknown) => listeners.add(fn),
    off: (_name: string, fn: unknown) => listeners.delete(fn),
  };
  const host = {
    destroyed: false, inputController: { collision: null }, cameraManager: { setCollision: vi.fn() },
    navCursor: { collision: null }, meshOverlay: null as MeshDebugOverlay | null,
    setCollisionProvider: vi.fn<(provider: ((environment: unknown) => unknown) | null) => void>(),
    setCollisionMesh: vi.fn<(points: Float32Array | null, indices: Uint32Array | null) => void>(),
  };
  const state = { hasCollision: false, hasCollisionOverlay: false, walkAllowed: false, cameraMode: "fly", collisionOverlayEnabled: false };
  const points = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
  const indices = new Uint32Array([0, 1, 2]);
  // Exactly the callbacks emitted by the postinstall patch, including the before-splat-load queue.
  runInNewContext(`(function () { ${init} this.setCollisionMesh(points, indices); ${attach} attachCollision(collisionReady); }).call(host)`, {
    host, points, indices, events, state, MeshCollision, MeshDebugOverlay,
    VoxelCollision: class {}, VoxelDebugOverlay: class {},
    sceneBound: {}, isWalkAllowed: () => true, renderer: "webgl", app: {}, camera: {}, config: {},
  });
  expect(host.inputController.collision).toBe(host.navCursor.collision);
  expect(host.cameraManager.setCollision).toHaveBeenLastCalledWith(host.inputController.collision);
  expect(state.walkAllowed).toBe(true);
  expect(listeners.size).toBe(1);
  expect(host.meshOverlay).toBeNull(); // Hidden debug geometry must not allocate a second million-triangle mesh.
  (Array.from(listeners)[0] as (value: boolean) => void)(true);
  const previous = host.meshOverlay!;
  host.setCollisionMesh(points, indices);
  expect(previous.destroy).toHaveBeenCalledOnce();
  expect(listeners.size).toBe(1);
  const environment = host.inputController.collision;
  const objectProvider = { kind: "object queries" };
  host.setCollisionProvider(base => ({ environment: base, objectProvider }));
  expect(host.cameraManager.setCollision).toHaveBeenLastCalledWith({ environment, objectProvider });
  expect(host.navCursor.collision).toEqual({ environment, objectProvider });
  host.setCollisionProvider(null);
  expect(host.inputController.collision).toBe(environment);
  state.cameraMode = "walk";
  host.setCollisionMesh(null, null);
  expect(host.inputController.collision).toBeNull();
  expect(host.navCursor.collision).toBeNull();
  expect(state.walkAllowed).toBe(false);
  expect(state.cameraMode).toBe("fly");
  expect(listeners.size).toBe(0);
});

it("reuses prepared environment geometry across fresh revision reads and ignores aborted preparations", async () => {
  const source = readFileSync(new URL("../node_modules/@playcanvas/supersplat-viewer/dist/viewer.js", import.meta.url), "utf8");
  const init = source.slice(source.indexOf("let collisionReady = null;"), source.indexOf("collisionLoad?.then"));
  const attach = source.slice(source.indexOf("attachCollision = (collision) => {"), source.indexOf("// collision may already have landed"));
  class MeshCollision {}
  const prepare = vi.fn<(points: Float32Array, indices: Uint32Array, signal: AbortSignal) => Promise<MeshCollision>>(async () => new MeshCollision());
  const host = {
    destroyed: false, inputController: { collision: null }, cameraManager: { setCollision: vi.fn() },
    navCursor: { collision: null }, meshOverlay: null,
    setCollisionMesh: vi.fn<(positions: Float32Array | null, indices: Uint32Array | null) => void>(),
    setCollisionMeshAsync: vi.fn<(positions: Float32Array, indices: Uint32Array, signal: AbortSignal) => Promise<void>>(),
  };
  const state = { hasCollision: false, hasCollisionOverlay: false, walkAllowed: false, cameraMode: "fly", collisionOverlayEnabled: false };
  runInNewContext(`(function () { ${init} ${attach} }).call(host)`, {
    host, state, MeshCollision, createMeshCollisionAsync: prepare,
    MeshDebugOverlay: class {}, VoxelCollision: class {}, VoxelDebugOverlay: class {},
    events: { on: vi.fn(), off: vi.fn() }, sceneBound: {}, isWalkAllowed: () => true,
    app: {}, camera: {}, config: {},
  });
  const positions = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
  const indices = new Uint32Array([0, 1, 2]);
  await host.setCollisionMeshAsync(positions, indices, new AbortController().signal);
  const collision = host.inputController.collision;
  host.setCollisionMesh(null, null);
  await host.setCollisionMeshAsync(positions, indices, new AbortController().signal);
  expect(prepare).toHaveBeenCalledOnce();
  expect(host.inputController.collision).toBe(collision);
  expect(state.walkAllowed).toBe(true);

  let finish!: (value: MeshCollision) => void;
  prepare.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  const controller = new AbortController();
  const pending = host.setCollisionMeshAsync(positions.slice(), indices, controller.signal);
  controller.abort();
  finish(new MeshCollision());
  await pending;
  expect(host.inputController.collision).toBe(collision);
});
