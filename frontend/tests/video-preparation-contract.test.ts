import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  calculateVideoPreparationChecksum,
  fitVideoDimensions,
  parseVideoNormalizationCapability,
  parseVideoNormalizationProfile,
  parseVideoPreparationManifest,
  preservesSdrColorMetadata,
  verifyVideoPreparationChecksum,
  VIDEO_NORMALIZATION_PROFILE_V1,
} from "../src/lib/contracts/videoPreparation";

function sharedFixture(): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(process.cwd(), "../fixtures/contracts/video_preparation_v1.json"), "utf8")) as Record<string, unknown>;
}

describe("video normalization contract v1", () => {
  it("uses the shared checksum-bound 720p profile without depending on object key order", () => {
    const fixture = sharedFixture();
    const profile = JSON.parse(JSON.stringify(fixture.profile)) as Record<string, unknown>;
    const presets = profile.presets as Array<Record<string, unknown>>;
    presets[0] = Object.fromEntries(Object.entries(presets[0]).reverse());

    expect(parseVideoNormalizationProfile(profile)).toEqual(VIDEO_NORMALIZATION_PROFILE_V1);
    expect(() => parseVideoNormalizationProfile({ ...profile, unexpected: true })).toThrow();
  });

  it("distinguishes supported capability from explicit input-specific blockers", () => {
    const fixture = sharedFixture();
    expect(parseVideoNormalizationCapability(fixture.capability_supported).status).toBe("supported");
    expect(parseVideoNormalizationCapability(fixture.capability_unsupported).blockers).toEqual(["hdr_unsupported"]);

    const broken = JSON.parse(JSON.stringify(fixture.capability_unsupported)) as Record<string, unknown>;
    broken.available_storage_bytes = null;
    expect(() => parseVideoNormalizationCapability(broken)).toThrow(/blockers/);
  });

  it("parses a preparation receipt and matches Python's canonical identity", async () => {
    const manifest = parseVideoPreparationManifest(sharedFixture().preparation_manifest);
    await verifyVideoPreparationChecksum(manifest);
    const { preparation_checksum, ...payload } = manifest;
    await expect(calculateVideoPreparationChecksum(payload)).resolves.toBe(preparation_checksum);
  });

  it("accepts portrait input after rotation and bounds output by the selected preset", () => {
    const manifest = JSON.parse(JSON.stringify(sharedFixture().preparation_manifest)) as Record<string, unknown>;
    const source = manifest.source_video as Record<string, unknown>;
    const prepared = manifest.prepared_video as Record<string, unknown>;
    source.display_width = 1080;
    source.display_height = 1920;
    source.rotation_degrees = 90;
    prepared.coded_width = 720;
    prepared.coded_height = 1280;
    prepared.display_width = 720;
    prepared.display_height = 1280;
    (manifest.pixel_transform as Record<string, unknown>).matrix = [[0, -2 / 3, 720], [2 / 3, 0, 0], [0, 0, 1]];

    const parsed = parseVideoPreparationManifest(manifest);
    expect(parsed.source_video.rotation_degrees).toBe(90);
    expect(parsed.prepared_video.display_height).toBe(1280);
  });

  it("accepts non-square source pixels only with an explicit coded-to-output transform", () => {
    const manifest = JSON.parse(JSON.stringify(sharedFixture().preparation_manifest)) as Record<string, unknown>;
    const source = manifest.source_video as Record<string, unknown>;
    source.coded_width = 1440;
    source.sample_aspect_ratio = { numerator: 4, denominator: 3 };
    (manifest.pixel_transform as Record<string, unknown>).matrix = [[8 / 9, 0, 0], [0, 2 / 3, 0], [0, 0, 1]];

    expect(parseVideoPreparationManifest(manifest).source_video.sample_aspect_ratio).toEqual({ numerator: 4, denominator: 3 });
  });

  it("allows standard SDR defaults when source colorimetry is absent and rejects HDR output", () => {
    const bt709 = { primaries: "bt709", transfer: "bt709", matrix: "bt709", range: "limited" };
    expect(preservesSdrColorMetadata(null, bt709)).toBe(true);
    expect(preservesSdrColorMetadata(null, {
      primaries: "bt2020", transfer: "bt709", matrix: "bt2020-ncl", range: "limited",
    })).toBe(true);
    expect(preservesSdrColorMetadata({ ...bt709, range: null }, bt709)).toBe(true);
    expect(preservesSdrColorMetadata(bt709, { ...bt709, transfer: "pq" })).toBe(false);
    expect(preservesSdrColorMetadata(null, { ...bt709, transfer: "hlg" })).toBe(false);
    expect(preservesSdrColorMetadata(bt709, null)).toBe(false);
  });

  it("fits landscape, portrait, 4:3 and low-resolution media without upscaling", () => {
    expect(fitVideoDimensions(1920, 1080, "720p")).toEqual({ width: 1280, height: 720 });
    expect(fitVideoDimensions(1080, 1920, "720p")).toEqual({ width: 720, height: 1280 });
    expect(fitVideoDimensions(1440, 1080, "720p")).toEqual({ width: 960, height: 720 });
    expect(fitVideoDimensions(640, 480, "1080p")).toEqual({ width: 640, height: 480 });
    expect(fitVideoDimensions(641, 481, "1080p")).toEqual({ width: 640, height: 480 });
    expect(() => fitVideoDimensions(1, 480, "720p")).toThrow(/at least two pixels/);
  });

  it("rejects output rotation metadata, unsupported codecs and altered frame-map claims", () => {
    const fixture = sharedFixture();
    const rotated = JSON.parse(JSON.stringify(fixture.preparation_manifest)) as Record<string, unknown>;
    (rotated.prepared_video as Record<string, unknown>).rotation_degrees = 90;
    expect(() => parseVideoPreparationManifest(rotated)).toThrow(/disagree/);

    const codec = JSON.parse(JSON.stringify(fixture.preparation_manifest)) as Record<string, unknown>;
    (codec.prepared_video as Record<string, unknown>).codec = "hevc";
    expect(() => parseVideoPreparationManifest(codec)).toThrow(/disagree/);

    const map = JSON.parse(JSON.stringify(fixture.preparation_manifest)) as Record<string, unknown>;
    (map.frame_map as Record<string, unknown>).entry_count = 2;
    expect(() => parseVideoPreparationManifest(map)).toThrow(/disagree/);

    const audio = JSON.parse(JSON.stringify(fixture.preparation_manifest)) as Record<string, unknown>;
    (audio.source_video as Record<string, unknown>).audio_track_count = 2;
    expect(() => parseVideoPreparationManifest(audio)).toThrow(/audio disposition/);
  });

  it("rejects a stale preparation content checksum", async () => {
    const manifest = parseVideoPreparationManifest(sharedFixture().preparation_manifest);
    const changed = { ...manifest, implementation_version: "changed" };
    await expect(verifyVideoPreparationChecksum(changed)).rejects.toThrow(/checksum/);
  });
});
