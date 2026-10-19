import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { colliderGlb } from "./helpers/collider-glb";

let load: typeof import("@/features/viewer/collision-mesh").loadCollisionMesh;
const controllers: AbortController[] = [];
const signal = () => { const controller = new AbortController(); controllers.push(controller); return controller.signal; };
const reply = (etag = '"same:display"') => new Response(colliderGlb({ frame: "display" }), { headers: { ETag: etag } });
const url = (revision: number, frame = "display", job = "j") => `/api/v1/jobs/${job}/walk-collision/collision.glb?scene_revision=rev-${revision}&frame=${frame}`;

beforeEach(async () => {
  vi.resetModules();
  load = (await import("@/features/viewer/collision-mesh")).loadCollisionMesh;
});
afterEach(() => {
  controllers.splice(0).forEach((controller) => controller.abort());
  vi.unstubAllGlobals();
});

it("shares one request and decode across physics and the viewer, including a later subscriber", async () => {
  const fetcher = vi.fn(async () => reply());
  vi.stubGlobal("fetch", fetcher);
  const first = load(url(1), signal());
  const second = load(url(1), signal());
  const mesh = await first;
  expect(await second).toBe(mesh);
  expect(await load(url(1), signal())).toBe(mesh);
  expect(fetcher).toHaveBeenCalledOnce();
});

it("validates every new revision, then reuses unchanged geometry by scoped server ETag", async () => {
  const second = reply();
  const readBody = vi.spyOn(second, "arrayBuffer");
  const fetcher = vi.fn().mockResolvedValueOnce(reply()).mockResolvedValueOnce(second);
  vi.stubGlobal("fetch", fetcher);
  const mesh = await load(url(1), signal());
  expect(await load(url(2), signal())).toBe(mesh);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(readBody).not.toHaveBeenCalled();
});

it("never substitutes cached geometry for a stale revision rejected by the API", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(reply()).mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "revision changed" }), { status: 409 }),
  ));
  await load(url(1), signal());
  await expect(load(url(2), signal())).rejects.toThrow("revision changed");
});

it("decodes a changed removal mask and keeps job/frame identities separate", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(reply()).mockResolvedValueOnce(reply('"changed:display"'))
    .mockResolvedValueOnce(reply('"changed:display"')).mockResolvedValueOnce(reply('"changed:display"')));
  const first = await load(url(1), signal());
  const changed = await load(url(2), signal());
  expect(changed).not.toBe(first);
  expect(await load(url(2, "canonical"), signal())).not.toBe(changed);
  expect(await load(url(2, "display", "other"), signal())).not.toBe(changed);
});

it("cancels only the departing subscriber; cancels the fetch when the last effect releases it", async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; }));
  vi.stubGlobal("fetch", fetcher);
  const a = signal(), b = signal();
  const first = load(url(1), a), second = load(url(1), b);
  controllers[0].abort();
  await expect(first).rejects.toMatchObject({ name: "AbortError" });
  const underlying = (fetcher.mock.calls[0] as unknown as [string, { signal: AbortSignal }])[1].signal;
  expect(underlying.aborted).toBe(false);
  finish(reply());
  await second;
  controllers[1].abort();
  expect(underlying.aborted).toBe(true);
});

it("does not decode a late response after all subscribers leave", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
  const pending = load(url(1), signal());
  controllers[0].abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  const response = reply();
  const readBody = vi.spyOn(response, "arrayBuffer");
  finish(response);
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(readBody).not.toHaveBeenCalled();
});

it("does not cache a corrupt mesh and allows a fresh attempt", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3])))
    .mockResolvedValueOnce(reply()));
  await expect(load(url(1), signal())).rejects.toThrow(/GLB/);
  await expect(load(url(1), signal())).resolves.toHaveProperty("indices");
});
