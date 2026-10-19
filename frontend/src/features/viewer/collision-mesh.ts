import { parseGlbMeshAsync, type TriangleMesh } from "./glb-mesh";

interface Load {
  controller: AbortController;
  promise: Promise<TriangleMesh>;
  users: number;
}

const loads = new Map<string, Load>();
// Keep at most two decoded frames. Every new revision URL still requires an authorized HTTP read.
const decoded = new Map<string, TriangleMesh>();

async function read(url: string, signal: AbortSignal): Promise<TriangleMesh> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    throw new Error(typeof detail === "string" ? detail : `Không tải được lưới va chạm (HTTP ${response.status}).`);
  }
  signal.throwIfAborted();
  const etag = response.headers?.get("ETag");
  const scope = new URL(url, window.location.origin);
  scope.searchParams.delete("scene_revision");
  const identity = etag ? `${scope.href}:${etag}` : null;
  const previous = identity ? decoded.get(identity) : undefined;
  if (previous) {
    await response.body?.cancel();
    signal.throwIfAborted();
    return previous;
  }
  const mesh = await parseGlbMeshAsync(await response.arrayBuffer(), signal);
  signal.throwIfAborted();
  if (identity) {
    decoded.set(identity, mesh);
    while (decoded.size > 2) decoded.delete(decoded.keys().next().value!);
  }
  return mesh;
}

/** Share an in-flight/active URL; abort the request when its last effect releases it. */
export function loadCollisionMesh(url: string, signal: AbortSignal): Promise<TriangleMesh> {
  if (signal.aborted) return Promise.reject(signal.reason);
  let load = loads.get(url);
  if (!load) {
    const controller = new AbortController();
    load = { controller, users: 0, promise: read(url, controller.signal) };
    loads.set(url, load);
  }
  const current = load;
  current.users++;
  return new Promise<TriangleMesh>((resolve, reject) => {
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      signal.removeEventListener("abort", abort);
      if (--current.users === 0) {
        current.controller.abort();
        if (loads.get(url) === current) loads.delete(url);
      }
    };
    const abort = () => { release(); reject(signal.reason); };
    signal.addEventListener("abort", abort, { once: true });
    current.promise.then(
      (mesh) => { if (!signal.aborted) resolve(mesh); },
      (error: unknown) => { release(); reject(error); },
    );
  });
}
