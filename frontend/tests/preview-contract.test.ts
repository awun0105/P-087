import { describe, expect, it } from "vitest";
import { parsePreview } from "../src/lib/contracts/preview";

function fixture() {
  const ref = (type: string, path: string, stage = "ST-VISUAL-RECON") => ({
    artifact_type: type, schema_version: "1.0", job_id: "job-1", producer_stage: stage,
    artifact_uri: `artifact://jobs/job-1/attempts/a1/${path}`, artifact_checksum: `sha256:${"a".repeat(64)}`, data_class: "derived",
  });
  return {
    schema_version: "1.0", artifact_type: "ReconstructionPreview", job_id: "job-1", attempt_id: "a1",
    source_input_checksum: `sha256:${"b".repeat(64)}`, format: "gaussian_sog", producer: "brush", producer_version: "fixture",
    metric_status: "UNCONFIRMED", coordinate_frame: "sfm_world", unit: "arbitrary",
    delivery_ref: ref("GaussianSOG", "rec04/scene.sog"), source_visual_ref: ref("BrushVisualArtifact", "rec04/visual.json"),
    camera_pose_ref: ref("CameraPoseArtifact", "rec03/poses.json", "ST-CAMERA-POSE"),
  };
}

describe("raw reconstruction preview API boundary", () => {
  it("accepts the raw contract without inventing metric status", () => {
    expect(parsePreview(fixture(), "job-1").unit).toBe("arbitrary");
  });

  it("rejects mismatched job, metric claims, traversal and non-product refs", () => {
    expect(() => parsePreview(fixture(), "job-2")).toThrow();
    expect(() => parsePreview({ ...fixture(), metric_status: "CONFIRMED" }, "job-1")).toThrow();
    for (const change of [
      { artifact_uri: "artifact://jobs/job-1/attempts/a1/../scene.sog" },
      { data_class: "ground_truth" }, { artifact_checksum: "not-a-hash" }, { producer_stage: "ST-COLLIDER" },
    ]) {
      const value = fixture();
      expect(() => parsePreview({ ...value, delivery_ref: { ...value.delivery_ref, ...change } }, "job-1")).toThrow();
    }
  });
});
