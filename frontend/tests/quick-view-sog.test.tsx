/** T-068: viewer dùng bản xem nhanh khi máy chủ đã có; nút chất lượng đầy đủ quay về bản gốc; chưa có thì dùng bản gốc. */
import { act, fireEvent, render, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MetricSceneView } from "@/features/studio/MetricSceneView";
import { useQuickView } from "@/features/viewer/useQuickView";

const renderViewer = vi.hoisted(() => vi.fn());
vi.mock("@/features/viewer/shell-glow", () => ({ ShellGlowLayer: class { destroy = vi.fn(); setShell = vi.fn(); clear = vi.fn(); setHovered = vi.fn(); } }));
vi.mock("@/features/viewer/scene-overlay", () => ({ SceneOverlay: class {} }));
vi.mock("@/features/viewer/third-person", () => ({ WALK_EYE_HEIGHT_M: 1.3, ThirdPersonRig: class {} }));
vi.mock("@/features/viewer/PlayCanvasScene", async (original) => ({
  ...await original<typeof import("@/features/viewer/PlayCanvasScene")>(),
  usePlayCanvasCapability: () => ["ready", vi.fn()],
  PlayCanvasScene: (props: object) => { renderViewer(props); return <div data-testid="viewer-surface" />; },
}));

const ref = { artifact_uri: "artifact://jobs/job-a/rec04/scene.sog", artifact_checksum: `sha256:${"a".repeat(64)}` };
const reply = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body), headers: new Headers() }) as Response;

afterEach(() => vi.unstubAllGlobals());

describe("quick view (T-068)", () => {
  it("uses the quick copy when ready and switches to full quality on request", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ state: "ready" })));
    const { result } = renderHook(() => useQuickView("job-a", ref));
    expect(result.current.settled).toBe(false);
    await waitFor(() => expect(result.current.settled).toBe(true));
    expect(result.current.quick).toBe(true);
    expect(result.current.url).toContain("/artifacts/quick?");
    act(() => result.current.showFull());
    expect(result.current.quick).toBe(false);
    expect(result.current.url).toContain("/artifacts/content");
  });

  it("uses the full copy while the quick copy is building or unavailable", async () => {
    for (const state of ["building", "unavailable"]) {
      vi.stubGlobal("fetch", vi.fn(async () => reply({ state })));
      const { result } = renderHook(() => useQuickView("job-a", ref));
      await waitFor(() => expect(result.current.settled).toBe(true));
      expect(result.current.quick).toBe(false);
      expect(result.current.url).toContain("/artifacts/content");
    }
  });

  it("falls back to the full copy when the status request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ detail: "x" }, 500)));
    const { result } = renderHook(() => useQuickView("job-a", ref));
    await waitFor(() => expect(result.current.settled).toBe(true));
    expect(result.current.url).toContain("/artifacts/content");
  });
});

describe("Studio viewer quick view (T-068)", () => {
  it("opens the quick copy and swaps to full quality from the toolbar", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ state: "ready" })));
    render(<MetricSceneView jobId="job-a" visual={ref} cameras={[]} />);
    await waitFor(() => expect(renderViewer).toHaveBeenCalled());
    expect(renderViewer.mock.lastCall![0].contentUrl).toContain("/artifacts/quick?");
    const toolbar = render(renderViewer.mock.lastCall![0].extraControls);
    fireEvent.click(toolbar.getByRole("button", { name: "Chất lượng đầy đủ" }));
    toolbar.unmount();
    expect(renderViewer.mock.lastCall![0].contentUrl).toContain("/artifacts/content");
  });
});
