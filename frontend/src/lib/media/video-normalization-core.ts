import { sha256 } from "@noble/hashes/sha2.js";
import type {
  ClientVideoPreparationManifest,
  VideoFrameMapDescriptor,
  PositiveRational,
  VideoPixelTransform,
  VideoResolutionPreset,
  VideoStreamMetadata,
} from "@/lib/contracts/videoPreparation";

export const VIDEO_NORMALIZER_IMPLEMENTATION_ID = "mediabunny-webcodecs";
export const VIDEO_NORMALIZER_IMPLEMENTATION_VERSION = "1.61.3";
export const MAX_VIDEO_DURATION_SECONDS = 2 * 60 * 60;
export const MAX_DECODED_VIDEO_PIXELS = 12_582_912;
export const STORAGE_RESERVE_BYTES = 64 * 1024 * 1024;
export const FRAME_MAP_ROW_BYTES = 16;

export type VideoPreparationErrorCode =
  | "cancelled"
  | "invalid_input"
  | "unsupported_media"
  | "unsupported_codec"
  | "unsupported_audio"
  | "audio_omission_required"
  | "hdr_unsupported"
  | "storage_unavailable"
  | "storage_insufficient"
  | "duration_limit"
  | "pixel_limit"
  | "frame_map_limit"
  | "media_processing_failed"
  | "verification_failed";

export type VideoPreparationPhase = "hashing" | "probing" | "encoding" | "verifying";

export interface VideoPreparationWorkerResult {
  source_checksum: string;
  prepared_checksum: string;
  prepared_size_bytes: number;
  source_video: VideoStreamMetadata;
  prepared_video: VideoStreamMetadata;
  pixel_transform: VideoPixelTransform;
  frame_map: VideoFrameMapDescriptor;
  audio_disposition: ClientVideoPreparationManifest["audio_disposition"];
  output_file_name: string;
  frame_map_file_name: string;
}

export type VideoPreparationWorkerResponse =
  | { type: "progress"; request_id: string; phase: VideoPreparationPhase; progress: number }
  | { type: "complete"; request_id: string; result: VideoPreparationWorkerResult }
  | { type: "failure"; request_id: string; code: VideoPreparationErrorCode; message: string };

export class VideoPreparationError extends Error {
  constructor(
    readonly code: VideoPreparationErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "VideoPreparationError";
  }
}

/** Greedily selects the first source frame at least 1/30 s after the prior selection. */
export class PresentationFrameSelector {
  private lastSeenPts: number | null = null;
  private lastSelectedPts: number | null = null;

  constructor(private readonly timeResolution: number) {
    if (!Number.isSafeInteger(timeResolution) || timeResolution <= 0) {
      throw new VideoPreparationError("unsupported_media", "Video timestamp resolution is unsupported.");
    }
  }

  shouldKeep(pts: number): boolean {
    if (!Number.isSafeInteger(pts) || (this.lastSeenPts !== null && pts <= this.lastSeenPts)) {
      throw new VideoPreparationError(
        "unsupported_media",
        "Video presentation timestamps must be strictly increasing and representable.",
      );
    }
    this.lastSeenPts = pts;
    if (this.lastSelectedPts === null ||
        (BigInt(pts) - BigInt(this.lastSelectedPts)) * BigInt(30) >= BigInt(this.timeResolution)) {
      this.lastSelectedPts = pts;
      return true;
    }
    return false;
  }
}

export function timestampToTicks(timestampSeconds: number, timeResolution: number): number {
  const ticks = Math.round(timestampSeconds * timeResolution);
  if (!Number.isFinite(timestampSeconds) || !Number.isSafeInteger(ticks)) {
    throw new VideoPreparationError("unsupported_media", "Video presentation timestamp exceeds the supported range.");
  }
  return ticks;
}

export function timeBaseForResolution(timeResolution: number): PositiveRational {
  if (!Number.isSafeInteger(timeResolution) || timeResolution <= 0) {
    throw new VideoPreparationError("unsupported_media", "Video timestamp resolution is unsupported.");
  }
  return { numerator: 1, denominator: timeResolution };
}

export function simplifyPositiveRational(numerator: number, denominator: number): PositiveRational {
  if (!Number.isSafeInteger(numerator) || numerator <= 0 || !Number.isSafeInteger(denominator) || denominator <= 0) {
    throw new VideoPreparationError("unsupported_media", "Video pixel aspect ratio is unsupported.");
  }
  let left = numerator;
  let right = denominator;
  while (right !== 0) [left, right] = [right, left % right];
  return { numerator: numerator / left, denominator: denominator / left };
}

export function validateRightAngleTransformation(matrix: readonly number[]): void {
  if (matrix.length !== 9 || matrix.some((value) => !Number.isFinite(value)) ||
      Math.abs(matrix[2]!) > 1e-6 || Math.abs(matrix[5]!) > 1e-6 || Math.abs(matrix[8]! - 1) > 1e-6) {
    throw new VideoPreparationError("unsupported_media", "Video metadata uses an unsupported non-affine display transform.");
  }
  const [a, b, , c, d] = matrix;
  const rightAngle = (value: number) => [-1, 0, 1].some((candidate) => Math.abs(value - candidate) <= 1e-6);
  if (!rightAngle(a!) || !rightAngle(b!) || !rightAngle(c!) || !rightAngle(d!) ||
      Math.abs(a! * a! + b! * b! - 1) > 1e-6 ||
      Math.abs(c! * c! + d! * d! - 1) > 1e-6 ||
      Math.abs(a! * c! + b! * d!) > 1e-6) {
    throw new VideoPreparationError("unsupported_media", "Video metadata uses scaling or shear beyond rotation and flip.");
  }
}

type Matrix3 = VideoPixelTransform["matrix"];

function multiply3(left: Matrix3, right: Matrix3): Matrix3 {
  return [0, 1, 2].map((row) => [0, 1, 2].map((column) =>
    left[row][0] * right[0][column] + left[row][1] * right[1][column] + left[row][2] * right[2][column],
  )) as Matrix3;
}

/** Maps coded-pixel centers through SAR, clockwise rotation, horizontal flip and output resize. */
export function createVideoPixelTransform(options: {
  codedWidth: number;
  codedHeight: number;
  sampleAspectRatio: PositiveRational;
  rotationDegrees: 0 | 90 | 180 | 270;
  flipHorizontal: boolean;
  outputWidth: number;
  outputHeight: number;
}): VideoPixelTransform {
  const { codedWidth, codedHeight, sampleAspectRatio, rotationDegrees, flipHorizontal, outputWidth, outputHeight } = options;
  const values = [codedWidth, codedHeight, outputWidth, outputHeight];
  if (values.some((value) => !Number.isSafeInteger(value) || value < 2) ||
      !Number.isSafeInteger(sampleAspectRatio.numerator) || sampleAspectRatio.numerator <= 0 ||
      !Number.isSafeInteger(sampleAspectRatio.denominator) || sampleAspectRatio.denominator <= 0 ||
      ![0, 90, 180, 270].includes(rotationDegrees)) {
    throw new VideoPreparationError("unsupported_media", "Video display transform metadata is unsupported.");
  }

  const sar = sampleAspectRatio.numerator / sampleAspectRatio.denominator;
  const squarePixelWidth = codedWidth * sar;
  const squarePixelHeight = codedHeight;
  const sarTransform: Matrix3 = [
    [sar, 0, (sar - 1) / 2],
    [0, 1, 0],
    [0, 0, 1],
  ];

  let rotation: Matrix3;
  let displayWidth: number;
  let displayHeight: number;
  switch (rotationDegrees) {
    case 90:
      rotation = [[0, -1, squarePixelHeight - 1], [1, 0, 0], [0, 0, 1]];
      displayWidth = squarePixelHeight;
      displayHeight = squarePixelWidth;
      break;
    case 180:
      rotation = [[-1, 0, squarePixelWidth - 1], [0, -1, squarePixelHeight - 1], [0, 0, 1]];
      displayWidth = squarePixelWidth;
      displayHeight = squarePixelHeight;
      break;
    case 270:
      rotation = [[0, 1, 0], [-1, 0, squarePixelWidth - 1], [0, 0, 1]];
      displayWidth = squarePixelHeight;
      displayHeight = squarePixelWidth;
      break;
    default:
      rotation = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
      displayWidth = squarePixelWidth;
      displayHeight = squarePixelHeight;
  }

  const flip: Matrix3 = flipHorizontal
    ? [[-1, 0, displayWidth - 1], [0, 1, 0], [0, 0, 1]]
    : [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  const scaleX = outputWidth / displayWidth;
  const scaleY = outputHeight / displayHeight;
  const resize: Matrix3 = [
    [scaleX, 0, (scaleX - 1) / 2],
    [0, scaleY, (scaleY - 1) / 2],
    [0, 0, 1],
  ];

  return { matrix: multiply3(resize, multiply3(flip, multiply3(rotation, sarTransform))) };
}

export async function hashFileSha256(file: Blob): Promise<string> {
  const hash = sha256.create();
  const reader = file.stream().getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      hash.update(value);
    }
  } finally {
    reader.releaseLock();
  }
  return `sha256:${Array.from(hash.digest(), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export function normalizedVideoFileName(sourceName: string): string {
  const stem = sourceName.replace(/\.[^.]+$/, "").replace(/[\\/\u0000-\u001f]/g, "_").slice(0, 180) || "video";
  return `${stem}.prepared.mp4`;
}

export function presetBitrate(preset: VideoResolutionPreset): number {
  switch (preset) {
    case "1080p": return 8_000_000;
    case "720p": return 4_000_000;
    case "480p": return 2_000_000;
  }
}
