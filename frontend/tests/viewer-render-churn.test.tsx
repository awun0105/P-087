/** T-064: render lại trang không được đưa cho viewer prop mới khi dữ liệu 3D không đổi (mỗi prop mới = vẽ lại khung splat). */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectReviewView } from "@/features/studio/ObjectReviewView";
import { clearSceneCache } from "@/lib/api/studio";

const seen: Record<string, unknown>[] = [];
vi.mock("@/features/studio/StageViewer", () => ({ CollisionMeshCanvas: () => <div /> }));
vi.mock("@/features/studio/MetricSceneView", () => ({
  MetricSceneView: (props: Record<string, unknown>) => {
    seen.push(props);
    return <div data-testid="metric-scene" />;
  },
}));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getStageViews: vi.fn(async () => []),
}));

const ref = {
  artifact_type: "SceneObjectGeometry", schema_version: "1.0", artifact_uri: "artifact://jobs/job-a/rec06/scene.sog",
  artifact_checksum: "sha256:" + "a".repeat(64), data_class: "derived", producer_stage: "ST-OBJECT-ASSOC", job_id: "job-a",
};
const scene = { scene_revision: "rev-001", environment: { geometry_ref: ref, visual_ref: ref }, provenance: {}, objects: [] };
const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }) as Response;

beforeEach(() => {
  seen.length = 0;
  global.fetch = vi.fn().mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url.includes("/scene/catalog")) return reply({ classes: [], entries: [], physics_note: "" });
    if (url.includes("/scene/objectify")) return reply({ status: "idle", mode: null, awaiting_choice: false, object_centric: true, available: true, note: null, base_revision: null, result_revision: null, error: null, resource_wait: null, cancellation_requested: false });
    if (url.includes("/scene")) return reply({ scene });
    return reply(null);
  });
});
afterEach(() => clearSceneCache());

describe("viewer props stay stable across parent renders (T-064)", () => {
  it("keeps data props by reference when nothing in the scene changed", async () => {
    const view = render(<ObjectReviewView jobId="job-a" sceneStateControls={<p>a</p>} />);
    await screen.findByTestId("metric-scene");
    const before = seen.at(-1)!;
    for (let index = 0; index < 5; index += 1) view.rerender(<ObjectReviewView jobId="job-a" sceneStateControls={<p>{index}</p>} />);
    const after = seen.at(-1)!;
    expect(seen.length).toBeGreaterThan(1);
    for (const key of ["surfacePlanes", "inspection", "collisionDiagnostics", "cameras", "boxes", "objects", "shells", "physicsObjects", "onMarkSurface", "onFillSurface", "onRemoveSurface", "onTransform"]) {
      expect(after[key], key).toBe(before[key]);
    }
  });
});
