import { afterEach, describe, expect, it, vi } from "vitest";

import { clearSceneCache, getJobScene } from "@/lib/api/studio";

afterEach(() => { vi.unstubAllGlobals(); clearSceneCache(); });

const body = { scene: { scene_revision: "rev-002", objects: [] }, scene_reference: {} };

describe("one scene download per revision for the whole page (T-063)", () => {
  it("shares one request between components asking at the same time", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200, headers: { ETag: '"s1"' } }));
    vi.stubGlobal("fetch", fetchMock);
    const [first, second] = await Promise.all([getJobScene("job-1"), getJobScene("job-1")]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(first.ok && second.ok && first.data === second.data).toBe(true);
  });

  it("revalidates with If-None-Match and reuses the parsed scene on 304", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(body), { status: 200, headers: { ETag: '"s1"' } }))
      .mockResolvedValueOnce(new Response(null, { status: 304 }));
    vi.stubGlobal("fetch", fetchMock);
    const first = await getJobScene("job-1");
    const second = await getJobScene("job-1");
    expect((fetchMock.mock.calls[1][1] as RequestInit).headers).toMatchObject({ "If-None-Match": '"s1"' });
    expect(first.ok && second.ok && first.data === second.data).toBe(true);
  });

  it("returns errors without caching them", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "x" }), { status: 409 })));
    const result = await getJobScene("job-1");
    expect(result.ok).toBe(false);
  });
});

describe("package and review state share in-flight requests (T-063)", () => {
  it("asks the server once when two panels load the package together, and again later", async () => {
    const reply = () => new Response(JSON.stringify(null), { status: 404 });
    const fetchMock = vi.fn().mockImplementation(async () => reply());
    vi.stubGlobal("fetch", fetchMock);
    const { getSimulationPackage } = await import("@/lib/api/studio");
    await Promise.allSettled([getSimulationPackage("job-1"), getSimulationPackage("job-1")]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await getSimulationPackage("job-1").catch(() => null);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("asks the server once when two panels load the review state together", async () => {
    const state = { job_id: "job-1", scene_revision: "rev-002", package: null, decisions: [] };
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify(state), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { getReviewState } = await import("@/lib/api/studio");
    await Promise.allSettled([getReviewState("job-1"), getReviewState("job-1")]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
