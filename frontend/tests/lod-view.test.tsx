/** T-070: viewer mở bộ LOD khi máy chủ đã có (hiện bản thô ngay, mịn dần tới đủ chất lượng); chưa có thì mở SOG gốc. */
import { render, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MetricSceneView } from "@/features/studio/MetricSceneView";
import { useLodView } from "@/features/viewer/useLodView";

const renderViewer = vi.hoisted(() => vi.fn());
vi.mock("@/features/viewer/shell-glow", () => ({ ShellGlowLayer: class { destroy = vi.fn(); setShell = vi.fn(); clear = vi.fn(); setHovered = vi.fn(); } }));
vi.mock("@/features/viewer/scene-overlay", () => ({ SceneOverlay: class {} }));
vi.mock("@/features/viewer/third-person", () => ({ WALK_EYE_HEIGHT_M: 1.3, ThirdPersonRig: class {} }));
vi.mock("@/features/viewer/PlayCanvasScene", async (original) => ({
  ...await original<typeof import("@/features/viewer/PlayCanvasScene")>(),
  usePlayCanvasCapability: () => ["ready", vi.fn()],
  PlayCanvasScene: (props: object) => { renderViewer(props); return <div data-testid="viewer-surface" />; },
}));

const hex = "a".repeat(64);
const ref = { artifact_uri: "artifact://jobs/job-a/rec06/scene.sog", artifact_checksum: `sha256:${hex}` };
const reply = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body), headers: new Headers() }) as Response;

afterEach(() => vi.unstubAllGlobals());

describe("LOD view (T-070)", () => {
  it("opens the LOD index when the bundle exists", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => reply({ lodLevels: 3 }));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useLodView("job-a", ref));
    expect(result.current.settled).toBe(false);
    await waitFor(() => expect(result.current.settled).toBe(true));
    expect(result.current.lod).toBe(true);
    expect(result.current.url).toContain(`/api/v1/jobs/job-a/lod/${hex}/lod-meta.json`);
    expect(result.current.filename).toBe("lod-meta.json");
    expect(String(fetchMock.mock.calls[0][0])).toContain(`/lod/${hex}/lod-meta.json`);
  });

  it("falls back to the original SOG when there is no bundle or the request fails", async () => {
    for (const response of [reply({ detail: "x" }, 404), reply({ detail: "x" }, 500)]) {
      vi.stubGlobal("fetch", vi.fn(async () => response));
      const { result } = renderHook(() => useLodView("job-a", ref));
      await waitFor(() => expect(result.current.settled).toBe(true));
      expect(result.current.lod).toBe(false);
      expect(result.current.url).toContain("/artifacts/content");
      expect(result.current.filename).toBe("scene.sog");
    }
  });

  it("Studio viewer streams the LOD bundle with its index file name", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ lodLevels: 3 })));
    render(<MetricSceneView jobId="job-a" visual={ref} cameras={[]} />);
    await waitFor(() => expect(renderViewer).toHaveBeenCalled());
    const props = renderViewer.mock.lastCall![0];
    expect(props.contentUrl).toContain("/lod-meta.json");
    expect(props.contentFilename).toBe("lod-meta.json");
  });
});
