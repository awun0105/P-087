/** T-065: bước Collision mesh chỉ tải lưới (0,1–1 MB); SOG chỉ tải khi bấm "Hiện kèm 3DGS". */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StageViewer } from "@/features/studio/StageViewer";
import { getStageViews } from "@/lib/api/studio";
import type { StageView } from "@/lib/contracts/studio";

vi.mock("@/lib/api/studio", () => ({ getStageViews: vi.fn() }));
vi.mock("@/features/viewer/PlayCanvasScene", () => ({
  usePlayCanvasCapability: () => ["available", vi.fn()],
  PlayCanvasScene: () => <div>Gaussian renderer</div>,
  INITIAL_RUNTIME: { loaded: false, progress: 0, graphicsBackend: "unknown", hasCollision: false, walkAllowed: false, cameraMode: "orbit" },
}));
vi.mock("@/features/studio/MetricSceneView", () => ({ MetricSceneView: () => <div>Metric renderer</div> }));

const ref = (name: string) => ({ artifact_type: "x", artifact_uri: `artifact://jobs/job-a/${name}`, artifact_checksum: `sha256:${"a".repeat(64)}` });
const metric: StageView = { stage_id: "ST-METRIC", kind: "gaussian", title: "3DGS mét", note: "", unit: "meter", refs: [ref("metric.sog")], cameras: [] };
const mesh: StageView = { stage_id: "ST-RGB-GEOMETRY", kind: "mesh", title: "Collision mesh", note: "", unit: "meter", refs: [ref("collision.glb")], cameras: [] };

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = vi.fn(() => new Promise<Response>(() => undefined));
  vi.mocked(getStageViews).mockResolvedValue([metric, mesh]);
});

describe("collision mesh step loads only the mesh (T-065)", () => {
  it("shows the mesh alone until the user asks for the 3DGS", async () => {
    render(<StageViewer jobId="job-a" stageId="ST-RGB-GEOMETRY" />);
    const button = await screen.findByRole("button", { name: "Hiện kèm 3DGS" });
    expect(screen.queryByText("Metric renderer")).toBeNull();
    expect(vi.mocked(global.fetch).mock.calls.map(([url]) => String(url)).some((url) => url.includes("collision.glb"))).toBe(true);
    fireEvent.click(button);
    expect(screen.getByText("Metric renderer")).toBeInTheDocument();
  });
});
