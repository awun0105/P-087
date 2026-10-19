import { afterEach, expect, it, vi } from "vitest";
import { createMeshCollision, createMeshCollisionAsync } from "@playcanvas/supersplat-viewer/viewer";
import { parseGlbMesh, parseGlbMeshAsync } from "@/features/viewer/glb-mesh";
import { colliderGlb } from "./helpers/collider-glb";

afterEach(() => vi.restoreAllMocks());

it("async GLB decoding keeps the same vertices, indices and validation as the synchronous reader", async () => {
  const bytes = colliderGlb();
  expect(await parseGlbMeshAsync(bytes)).toEqual(parseGlbMesh(bytes));
  await expect(parseGlbMeshAsync(bytes.slice(0, -4))).rejects.toThrow(/GLB/);
  const invalid = colliderGlb({ edit: (document) => { document.nodes[1].matrix![12] = 1; } });
  await expect(parseGlbMeshAsync(invalid)).rejects.toThrow(/transform/);
});

it("cooperative BVH matches the pinned synchronous collision queries", async () => {
  const { positions, indices } = parseGlbMesh(colliderGlb({ frame: "display" }));
  const sync = createMeshCollision(positions, indices);
  const async = await createMeshCollisionAsync(positions, indices);
  expect(async.queryRay(0, 5, 0, 0, -1, 0, 20)).toEqual(sync.queryRay(0, 5, 0, 0, -1, 0, 20));
  expect(async.queryRay(10, 5, 0, 0, -1, 0, 20)).toBeNull();
  for (const collision of [sync, async]) {
    const push = { x: 0, y: 0, z: 0 };
    expect(collision.querySphere(0, 1.5, 0, .1, push)).toBe(true);
  }
});

it("lets UI tasks run while building and stops a superseded BVH before installing it", async () => {
  let clock = 0;
  vi.spyOn(performance, "now").mockImplementation(() => clock += 10);
  const { positions, indices } = parseGlbMesh(colliderGlb({ frame: "display" }));
  const controller = new AbortController();
  let taskRan = false;
  const task = setTimeout(() => { taskRan = true; controller.abort(); }, 0);
  await expect(createMeshCollisionAsync(positions, indices, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  clearTimeout(task);
  expect(taskRan).toBe(true);
  expect(indices).toEqual(parseGlbMesh(colliderGlb()).indices);
});

it("cancels decoding and BVH construction before work begins", async () => {
  const signal = AbortSignal.abort();
  await expect(parseGlbMeshAsync(colliderGlb(), signal)).rejects.toMatchObject({ name: "AbortError" });
  await expect(createMeshCollisionAsync(new Float32Array(), new Uint32Array(), signal)).rejects.toMatchObject({ name: "AbortError" });
});
