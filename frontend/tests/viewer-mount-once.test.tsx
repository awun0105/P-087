/** T-064: scene về trước danh sách camera → viewer vẫn chỉ dựng một lần, với camera cuối cùng (SOG môi trường tải một lần). */
import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectReviewView } from "@/features/studio/ObjectReviewView";
import { clearSceneCache, getStageViews } from "@/lib/api/studio";

const mounts: unknown[] = [];
vi.mock("@/features/studio/StageViewer", () => ({ CollisionMeshCanvas: () => <div /> }));
vi.mock("@/features/studio/MetricSceneView", () => ({
  MetricSceneView: ({ cameras }: { cameras: unknown }) => {
    // Viewer thật dựng lại khi `cameras` đổi; đếm như vậy.
    useEffect(() => { mounts.push(cameras); }, [cameras]);
    return <div data-testid="metric-scene" />;
  },
}));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getStageViews: vi.fn(),
}));

const ref = {
  artifact_type: "SceneObjectGeometry", schema_version: "1.0", artifact_uri: "artifact://jobs/job-a/rec06/scene.sog",
  artifact_checksum: "sha256:" + "a".repeat(64), data_class: "derived", producer_stage: "ST-OBJECT-ASSOC", job_id: "job-a",
};
const scene = { scene_revision: "rev-001", environment: { geometry_ref: ref, visual_ref: ref }, provenance: {}, objects: [] };
const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }) as Response;
const camera = { position: [0, 0, 1], rotation_xyzw: [0, 0, 0, 1] };

beforeEach(() => {
  mounts.length = 0;
  global.fetch = vi.fn().mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url.includes("/scene/catalog")) return reply({ classes: [], entries: [], physics_note: "" });
    if (url.includes("/scene/objectify")) return reply({ status: "idle", mode: null, awaiting_choice: false, object_centric: true, available: true, note: null, base_revision: null, result_revision: null, error: null, resource_wait: null, cancellation_requested: false });
    if (url.includes("/scene")) return reply({ scene });
    return reply(null);
  });
});
afterEach(() => clearSceneCache());

describe("viewer mounts once per page (T-064)", () => {
  it("waits for the camera list when the scene arrives first", async () => {
    let resolveViews!: (value: unknown) => void;
    vi.mocked(getStageViews).mockReturnValue(new Promise((resolve) => { resolveViews = resolve; }) as never);
    render(<ObjectReviewView jobId="job-a" />);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    await act(async () => { resolveViews([{ kind: "gaussian", unit: "meter", cameras: [camera] }]); });
    await screen.findByTestId("metric-scene");
    expect(mounts).toHaveLength(1);
    expect(mounts[0]).toEqual([camera]);
  });

  it("still opens the viewer when the camera list fails", async () => {
    vi.mocked(getStageViews).mockRejectedValue(new Error("boom"));
    render(<ObjectReviewView jobId="job-a" />);
    await screen.findByTestId("metric-scene");
    expect(mounts).toHaveLength(1);
  });
});
