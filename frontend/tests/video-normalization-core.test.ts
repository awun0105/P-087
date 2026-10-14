import { describe, expect, it } from "vitest";
import {
  createVideoPixelTransform,
  hashFileSha256,
  normalizedVideoFileName,
  PresentationFrameSelector,
  timestampToTicks,
  timeBaseForResolution,
  validateRightAngleTransformation,
} from "../src/lib/media/video-normalization-core";

function selectedFrameIndices(frameRateNumerator: number, frameRateDenominator: number, count = 120): number[] {
  const timeResolution = 90_000;
  const selector = new PresentationFrameSelector(timeResolution);
  return Array.from({ length: count }, (_, index) => index).filter((index) => {
    const pts = Math.round(index * timeResolution * frameRateDenominator / frameRateNumerator);
    return selector.shouldKeep(pts);
  });
}

describe("bounded client video normalization primitives", () => {
  it.each([
    [24, 1],
    [25, 1],
    [30_000, 1_001],
    [30, 1],
  ])("preserves every frame at or below 30 FPS (%s/%s)", (numerator, denominator) => {
    expect(selectedFrameIndices(numerator, denominator)).toEqual(Array.from({ length: 120 }, (_, index) => index));
  });

  it("caps 60 FPS on presentation timestamps without generating duplicate frames", () => {
    expect(selectedFrameIndices(60, 1, 12)).toEqual([0, 2, 4, 6, 8, 10]);
  });

  it("uses the presentation timeline across VFR gaps and rejects duplicate or unordered PTS", () => {
    const selector = new PresentationFrameSelector(90_000);
    expect([0, 450, 3_000, 3_100, 6_000].filter((pts) => selector.shouldKeep(pts))).toEqual([0, 3_000, 6_000]);
    expect(() => new PresentationFrameSelector(90_000).shouldKeep(Number.NaN)).toThrow(/timestamps/);
    const invalid = new PresentationFrameSelector(90_000);
    invalid.shouldKeep(3000);
    expect(() => invalid.shouldKeep(3000)).toThrow(/strictly increasing/);
  });

  it("maps nonzero presentation timestamps through the declared rational timebase", () => {
    expect(timestampToTicks(2.5, 90_000)).toBe(225_000);
    expect(timeBaseForResolution(90_000)).toEqual({ numerator: 1, denominator: 90_000 });
  });

  it("accepts only orthogonal rotation/flip metadata and rejects affine scale or shear", () => {
    expect(() => validateRightAngleTransformation([0, 1, 0, -1, 0, 0, 1080, 0, 1])).not.toThrow();
    expect(() => validateRightAngleTransformation([1.2, 0, 0, 0, 1, 0, 0, 0, 1])).toThrow(/scaling or shear/);
  });

  it("records pixel-center transforms for rotation, SAR correction, flip and even-size resize", () => {
    const rotated = createVideoPixelTransform({
      codedWidth: 1920,
      codedHeight: 1080,
      sampleAspectRatio: { numerator: 1, denominator: 1 },
      rotationDegrees: 90,
      flipHorizontal: false,
      outputWidth: 720,
      outputHeight: 1280,
    }).matrix;
    expect(rotated[0][0]).toBeCloseTo(0);
    expect(rotated[0][1]).toBeCloseTo(-2 / 3);
    expect(rotated[1][0]).toBeCloseTo(2 / 3);
    expect(rotated[2]).toEqual([0, 0, 1]);

    const nonSquare = createVideoPixelTransform({
      codedWidth: 1440,
      codedHeight: 1080,
      sampleAspectRatio: { numerator: 4, denominator: 3 },
      rotationDegrees: 0,
      flipHorizontal: true,
      outputWidth: 1280,
      outputHeight: 720,
    }).matrix;
    expect(nonSquare[0][0]).toBeLessThan(0);
    expect(nonSquare[1][1]).toBeGreaterThan(0);
    expect(nonSquare.flat().every(Number.isFinite)).toBe(true);
  });

  it("hashes Blob content incrementally and assigns a safe prepared filename", async () => {
    const chunks = [new TextEncoder().encode("a"), new TextEncoder().encode("bc")];
    const streamedBlob = {
      stream: () => new ReadableStream<Uint8Array>({
        pull(controller) {
          const next = chunks.shift();
          if (next) controller.enqueue(next);
          else controller.close();
        },
      }),
    } as Blob;
    await expect(hashFileSha256(streamedBlob)).resolves.toBe(
      "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
    expect(normalizedVideoFileName("../../warehouse\u0000walk.mov")).toBe(".._.._warehouse_walk.prepared.mp4");
  });
});
