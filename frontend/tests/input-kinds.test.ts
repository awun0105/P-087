import { describe, expect, it } from "vitest";

import { canCreateScene, describeDetection, inputKind, isGaussian, rejectFileName, rejectFileNameFor } from "@/features/studio/inputKinds";
import type { UploadRecord } from "@/lib/contracts/studio";

const BASE: UploadRecord = {
  upload_id: "upload-1",
  original_name: "scene.ply",
  media_type: "application/x-ply",
  size_bytes: 10,
  checksum: "sha256:x",
  artifact_uri: "artifact://jobs/upload-1/input/source.ply",
  received_at: "2026-09-29T00:00:00Z",
  project_ids: [],
};

describe("input kinds", () => {
  it("filters names early but leaves real detection to the server", () => {
    for (const ok of ["a.MP4", "b.mov", "c.ply", "d.sog", "e.zip"]) expect(rejectFileName(ok)).toBeNull();
    for (const bad of ["e.splat", "f.txt", "g"]) expect(rejectFileName(bad)).toMatch(/Chỉ nhận/);
  });

  it("treats records without input_kind as legacy video", () => {
    const legacy = { ...BASE, media_type: "video/mp4" as const, original_name: "kho.mp4" };
    expect(inputKind(legacy)).toBe("rgb_video");
    expect(canCreateScene(legacy)).toBe(true);
  });

  it("blocks scene creation until normalized media upload has server verification", () => {
    const pending = { ...BASE, media_type: "video/mp4" as const, input_kind: "rgb_video" as const, video_preparation_status: "pending" as const };
    const verified = { ...pending, video_preparation_status: "verified" as const };
    expect(canCreateScene(pending)).toBe(false);
    expect(canCreateScene(verified)).toBe(true);
  });

  it("describes detected 3DGS and blocks scene creation until import exists", () => {
    const ply: UploadRecord = {
      ...BASE,
      input_kind: "gaussian_ply",
      detection: {
        kind: "gaussian_ply",
        gaussian: { gaussian_count: 12000, sh_degree: 3, encoding: "binary_little_endian" },
        ply_member: null,
        colmap_dir: null,
        colmap_format: null,
      },
    };
    expect(describeDetection(ply)).toMatch(/Scene 3DGS \(\.ply\) · 12\.000 Gaussian · SH bậc 3/);
    expect(canCreateScene(ply)).toBe(false);
  });

  it("routes uploaded SOG to scene import without treating it as reconstruction input", () => {
    const sog: UploadRecord = {
      ...BASE,
      original_name: "external.sog",
      media_type: "application/x-sog",
      input_kind: "gaussian_sog",
      detection: {
        kind: "gaussian_sog",
        gaussian: null,
        sog: { format_version: 2, gaussian_count: 120, sh_degree: 1, model: "2dgs" },
        ply_member: null,
        colmap_dir: null,
        colmap_format: null,
      },
    };
    expect(isGaussian(sog)).toBe(true);
    expect(canCreateScene(sog)).toBe(false);
    expect(rejectFileNameFor("external.sog", "gaussian")).toBeNull();
    expect(rejectFileNameFor("external.sog", "video")).toMatch(/\.ply\/\.sog\/\.zip/);
    expect(describeDetection(sog)).toMatch(/Scene 3DGS \(\.sog\) · 120 Gaussian · SH bậc 1/);
  });
});
