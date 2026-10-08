/** Shared v1 contract for browser-side video preparation (AUD-23.S1). */

export type VideoResolutionPreset = "1080p" | "720p" | "480p";

export interface PositiveRational {
  numerator: number;
  denominator: number;
}

export interface VideoResolutionProfile {
  preset: VideoResolutionPreset;
  /** Orientation-independent bounds: portrait swaps these edges. */
  max_long_edge_px: number;
  max_short_edge_px: number;
  /** Initial candidate only; S5 must qualify bitrate against real captures. */
  target_bitrate_bps: number;
}

export interface VideoNormalizationProfile {
  schema_version: "1.0";
  profile_id: "real2sim_client_video";
  profile_version: "1";
  default_preset: VideoResolutionPreset;
  presets: VideoResolutionProfile[];
  max_frame_rate: PositiveRational;
  frame_rate_policy: "presentation_time_nearest_no_duplicate";
  container: "video/mp4";
  video_codec_family: "avc";
  bitrate_mode: "variable";
  allow_upscale: false;
  preserve_display_aspect: true;
  crop_policy: "none";
  orientation_policy: "apply_once_to_pixels";
  dimension_rounding: "even_down";
  max_duration_error_frames: number;
  max_frame_map_bytes: number;
  audio_policy: "preserve_compatible_or_explicit_omit";
  color_policy: "preserve_sdr_metadata_reject_hdr";
  profile_checksum: string;
}

export const VIDEO_NORMALIZATION_PROFILE_V1: VideoNormalizationProfile = {
  schema_version: "1.0",
  profile_id: "real2sim_client_video",
  profile_version: "1",
  default_preset: "720p",
  presets: [
    { preset: "1080p", max_long_edge_px: 1920, max_short_edge_px: 1080, target_bitrate_bps: 8_000_000 },
    { preset: "720p", max_long_edge_px: 1280, max_short_edge_px: 720, target_bitrate_bps: 4_000_000 },
    { preset: "480p", max_long_edge_px: 854, max_short_edge_px: 480, target_bitrate_bps: 2_000_000 },
  ],
  max_frame_rate: { numerator: 30, denominator: 1 },
  frame_rate_policy: "presentation_time_nearest_no_duplicate",
  container: "video/mp4",
  video_codec_family: "avc",
  bitrate_mode: "variable",
  allow_upscale: false,
  preserve_display_aspect: true,
  crop_policy: "none",
  orientation_policy: "apply_once_to_pixels",
  dimension_rounding: "even_down",
  max_duration_error_frames: 1,
  max_frame_map_bytes: 33_554_432,
  audio_policy: "preserve_compatible_or_explicit_omit",
  color_policy: "preserve_sdr_metadata_reject_hdr",
  profile_checksum: "sha256:b09fdfdea2c66d347387fcf3a21df107cb12e5a163fcc367a9bd53ec9e5a6ca7",
};

export type VideoNormalizationBlocker =
  | "secure_context_required"
  | "worker_unavailable"
  | "decoder_unsupported"
  | "encoder_unsupported"
  | "mp4_muxer_unavailable"
  | "storage_unknown"
  | "storage_insufficient"
  | "hdr_unsupported"
  | "audio_requires_explicit_omission"
  | "video_metadata_unsupported";

export interface VideoNormalizationCapability {
  schema_version: "1.0";
  profile_checksum: string;
  requested_preset: VideoResolutionPreset;
  secure_context: boolean;
  worker_available: boolean;
  decoder_supported: boolean;
  encoder_supported: boolean;
  mp4_muxer_available: boolean;
  video_metadata_supported: boolean;
  hdr_supported: boolean;
  audio_policy_satisfied: boolean;
  available_storage_bytes: number | null;
  required_storage_bytes: number;
  blockers: VideoNormalizationBlocker[];
  status: "supported" | "unsupported";
}

export interface ClientVideoFingerprint {
  original_name: string;
  size_bytes: number;
  last_modified_ms: number;
  /** Browser-declared only; it is not proof that the server received the original. */
  declared_source_checksum: string;
}

export interface VideoColorMetadata {
  primaries: string | null;
  transfer: string | null;
  matrix: string | null;
  range: string | null;
}

export interface VideoStreamMetadata {
  codec: string;
  coded_width: number;
  coded_height: number;
  /** Dimensions after display rotation and sample-aspect correction. */
  display_width: number;
  display_height: number;
  sample_aspect_ratio: PositiveRational;
  rotation_degrees: 0 | 90 | 180 | 270;
  start_pts: number;
  duration_ticks: number;
  time_base: PositiveRational;
  frame_rate: PositiveRational | null;
  frame_count: number;
  color: VideoColorMetadata | null;
  audio_track_count: number;
}

export interface VideoFrameBinding {
  schema_version: "1.0";
  output_frame_index: number;
  output_pts: number;
  source_frame_index: number;
  source_pts: number;
}

export interface VideoFrameMapDescriptor {
  format: "r2s_video_frame_map_jsonl_v1";
  checksum: string;
  size_bytes: number;
  entry_count: number;
  source_frame_count: number;
}

export interface VideoPixelTransform {
  /** Row-major map from source coded pixels to output, applying rotation and sample aspect once. */
  matrix: [[number, number, number], [number, number, number], [number, number, number]];
}

export interface ClientVideoPreparationManifest {
  schema_version: "1.0";
  profile_checksum: string;
  selected_preset: VideoResolutionPreset;
  implementation_id: string;
  implementation_version: string;
  source: ClientVideoFingerprint;
  prepared_file: { content_type: "video/mp4"; size_bytes: number; checksum: string };
  source_video: VideoStreamMetadata;
  prepared_video: VideoStreamMetadata;
  pixel_transform: VideoPixelTransform;
  frame_map: VideoFrameMapDescriptor;
  audio_disposition: "source_has_no_audio" | "preserved" | "omitted_with_user_consent";
  preparation_checksum: string;
}

type JsonRecord = Record<string, unknown>;

const PRESETS: readonly VideoResolutionPreset[] = ["1080p", "720p", "480p"];
const BLOCKERS: readonly VideoNormalizationBlocker[] = [
  "secure_context_required", "worker_unavailable", "decoder_unsupported", "encoder_unsupported",
  "mp4_muxer_unavailable", "storage_unknown", "storage_insufficient", "hdr_unsupported",
  "audio_requires_explicit_omission", "video_metadata_unsupported",
];

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: JsonRecord, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value);
}

function isChecksum(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}

function isPreset(value: unknown): value is VideoResolutionPreset {
  return typeof value === "string" && PRESETS.includes(value as VideoResolutionPreset);
}

function parseRational(value: unknown): value is PositiveRational {
  return isRecord(value) && hasExactKeys(value, ["numerator", "denominator"]) &&
    isPositiveInteger(value.numerator) && isPositiveInteger(value.denominator) &&
    gcd(value.numerator, value.denominator) === 1;
}

function gcd(a: number, b: number): number {
  let left = a;
  let right = b;
  while (right !== 0) [left, right] = [right, left % right];
  return left;
}

export function parseVideoNormalizationProfile(value: unknown): VideoNormalizationProfile {
  const keys = [
    "schema_version", "profile_id", "profile_version", "default_preset", "presets", "max_frame_rate",
    "frame_rate_policy", "container", "video_codec_family", "bitrate_mode", "allow_upscale",
    "preserve_display_aspect", "crop_policy", "orientation_policy", "dimension_rounding",
    "max_duration_error_frames", "max_frame_map_bytes", "audio_policy", "color_policy", "profile_checksum",
  ];
  if (!isRecord(value) || !hasExactKeys(value, keys) || value.schema_version !== "1.0" ||
      value.profile_id !== "real2sim_client_video" || value.profile_version !== "1" ||
      value.default_preset !== "720p" || !Array.isArray(value.presets) || value.presets.length !== 3 ||
      !parseRational(value.max_frame_rate) || value.max_frame_rate.numerator !== 30 ||
      value.max_frame_rate.denominator !== 1 || value.frame_rate_policy !== "presentation_time_nearest_no_duplicate" ||
      value.container !== "video/mp4" || value.video_codec_family !== "avc" || value.bitrate_mode !== "variable" ||
      value.allow_upscale !== false || value.preserve_display_aspect !== true || value.crop_policy !== "none" ||
      value.orientation_policy !== "apply_once_to_pixels" || value.dimension_rounding !== "even_down" ||
      value.max_duration_error_frames !== 1 || value.max_frame_map_bytes !== 33_554_432 ||
      value.audio_policy !== "preserve_compatible_or_explicit_omit" ||
      value.color_policy !== "preserve_sdr_metadata_reject_hdr" ||
      value.profile_checksum !== VIDEO_NORMALIZATION_PROFILE_V1.profile_checksum) {
    throw new Error("Video normalization profile v1 is not valid");
  }
  const expected = VIDEO_NORMALIZATION_PROFILE_V1.presets;
  const matches = value.presets.every((item, index) => {
    if (!isRecord(item) || !hasExactKeys(item, ["preset", "max_long_edge_px", "max_short_edge_px", "target_bitrate_bps"])) return false;
    const preset = expected[index];
    return item.preset === preset.preset && item.max_long_edge_px === preset.max_long_edge_px &&
      item.max_short_edge_px === preset.max_short_edge_px && item.target_bitrate_bps === preset.target_bitrate_bps;
  });
  if (!matches) throw new Error("Video normalization presets do not match v1");
  return value as unknown as VideoNormalizationProfile;
}

export interface VideoOutputDimensions {
  width: number;
  height: number;
}

/** Fit already oriented display-pixel dimensions into an orientation-independent preset, without upscaling. */
export function fitVideoDimensions(
  displayWidth: number,
  displayHeight: number,
  preset: VideoResolutionPreset,
  profile: VideoNormalizationProfile = VIDEO_NORMALIZATION_PROFILE_V1,
): VideoOutputDimensions {
  if (!isPositiveInteger(displayWidth) || !isPositiveInteger(displayHeight) || displayWidth < 2 || displayHeight < 2) {
    throw new Error("Video display dimensions must be safe positive integers of at least two pixels");
  }
  const bounds = profile.presets.find((item) => item.preset === preset);
  if (!bounds) throw new Error("Video resolution preset is not present in the active profile");
  const longEdge = Math.max(displayWidth, displayHeight);
  const shortEdge = Math.min(displayWidth, displayHeight);
  const scale = Math.min(1, bounds.max_long_edge_px / longEdge, bounds.max_short_edge_px / shortEdge);
  const width = Math.floor((displayWidth * scale) / 2) * 2;
  const height = Math.floor((displayHeight * scale) / 2) * 2;
  if (width < 2 || height < 2) throw new Error("Video is too small for even-dimension AVC encoding without upscaling");
  return { width, height };
}

export function parseVideoNormalizationCapability(value: unknown): VideoNormalizationCapability {
  const keys = [
    "schema_version", "profile_checksum", "requested_preset", "secure_context", "worker_available",
    "decoder_supported", "encoder_supported", "mp4_muxer_available", "video_metadata_supported",
    "hdr_supported", "audio_policy_satisfied", "available_storage_bytes", "required_storage_bytes", "blockers", "status",
  ];
  if (!isRecord(value) || !hasExactKeys(value, keys) || value.schema_version !== "1.0" ||
      value.profile_checksum !== VIDEO_NORMALIZATION_PROFILE_V1.profile_checksum || !isPreset(value.requested_preset) ||
      typeof value.secure_context !== "boolean" || typeof value.worker_available !== "boolean" ||
      typeof value.decoder_supported !== "boolean" || typeof value.encoder_supported !== "boolean" ||
      typeof value.mp4_muxer_available !== "boolean" || typeof value.video_metadata_supported !== "boolean" ||
      typeof value.hdr_supported !== "boolean" || typeof value.audio_policy_satisfied !== "boolean" ||
      (value.available_storage_bytes !== null && !isNonnegativeInteger(value.available_storage_bytes)) ||
      !isNonnegativeInteger(value.required_storage_bytes) || !Array.isArray(value.blockers) ||
      !value.blockers.every((item) => typeof item === "string" && BLOCKERS.includes(item as VideoNormalizationBlocker)) ||
      (value.status !== "supported" && value.status !== "unsupported")) {
    throw new Error("Video normalization capability is not valid");
  }
  const blockers = value.blockers as VideoNormalizationBlocker[];
  const detected: VideoNormalizationBlocker[] = [];
  if (!value.secure_context) detected.push("secure_context_required");
  if (!value.worker_available) detected.push("worker_unavailable");
  if (!value.decoder_supported) detected.push("decoder_unsupported");
  if (!value.encoder_supported) detected.push("encoder_unsupported");
  if (!value.mp4_muxer_available) detected.push("mp4_muxer_unavailable");
  if (!value.video_metadata_supported) detected.push("video_metadata_unsupported");
  if (!value.hdr_supported) detected.push("hdr_unsupported");
  if (!value.audio_policy_satisfied) detected.push("audio_requires_explicit_omission");
  if (value.available_storage_bytes === null) detected.push("storage_unknown");
  else if (value.available_storage_bytes < value.required_storage_bytes) detected.push("storage_insufficient");
  if (new Set(blockers).size !== blockers.length || blockers.length !== detected.length ||
      !detected.every((item) => blockers.includes(item)) ||
      (value.status === "supported" && blockers.length !== 0) ||
      (value.status === "unsupported" && blockers.length === 0)) {
    throw new Error("Video normalization capability contradicts its blockers");
  }
  return value as unknown as VideoNormalizationCapability;
}

function parseColor(value: unknown): value is VideoColorMetadata | null {
  if (value === null) return true;
  if (!isRecord(value) || !hasExactKeys(value, ["primaries", "transfer", "matrix", "range"])) return false;
  return ["primaries", "transfer", "matrix", "range"].every((key) =>
    value[key] === null || (typeof value[key] === "string" && value[key].length <= 128));
}

function parseVideoStream(value: unknown): value is VideoStreamMetadata {
  const keys = [
    "codec", "coded_width", "coded_height", "display_width", "display_height", "sample_aspect_ratio",
    "rotation_degrees", "start_pts", "duration_ticks", "time_base", "frame_rate", "frame_count", "color", "audio_track_count",
  ];
  return isRecord(value) && hasExactKeys(value, keys) && typeof value.codec === "string" &&
    value.codec.length > 0 && value.codec.length <= 128 && isPositiveInteger(value.coded_width) &&
      isPositiveInteger(value.coded_height) && isPositiveInteger(value.display_width) &&
    isPositiveInteger(value.display_height) && parseRational(value.sample_aspect_ratio) &&
    (value.rotation_degrees === 0 || value.rotation_degrees === 90 || value.rotation_degrees === 180 ||
      value.rotation_degrees === 270) && isInteger(value.start_pts) &&
    isPositiveInteger(value.duration_ticks) && parseRational(value.time_base) &&
    (value.frame_rate === null || parseRational(value.frame_rate)) && isPositiveInteger(value.frame_count) &&
    parseColor(value.color) && isNonnegativeInteger(value.audio_track_count);
}

function isAvcCodec(codec: string): boolean {
  const value = codec.toLowerCase();
  return value === "avc" || value === "h264" || value.startsWith("avc1.");
}

function isHdrTransfer(transfer: string | null): boolean {
  const normalized = (transfer ?? "").toLowerCase().replaceAll("_", "-").replaceAll(" ", "-");
  return normalized.includes("2084") || normalized.includes("arib-std-b67") || normalized === "pq" || normalized === "hlg";
}

/** Keep known source colorimetry and reject output that signals HDR. */
export function preservesSdrColorMetadata(
  source: VideoColorMetadata | null,
  prepared: VideoColorMetadata | null,
): boolean {
  if (prepared && isHdrTransfer(prepared.transfer)) return false;
  if (source === null) return true;
  if (prepared === null) return Object.values(source).every((value) => value === null);
  return (source.primaries === null || source.primaries === prepared.primaries) &&
    (source.transfer === null || source.transfer === prepared.transfer) &&
    (source.matrix === null || source.matrix === prepared.matrix) &&
    (source.range === null || source.range === prepared.range);
}

export function parseVideoPreparationManifest(value: unknown): ClientVideoPreparationManifest {
  const keys = [
    "schema_version", "profile_checksum", "selected_preset", "implementation_id", "implementation_version", "source",
    "prepared_file", "source_video", "prepared_video", "pixel_transform", "frame_map", "audio_disposition", "preparation_checksum",
  ];
  if (!isRecord(value) || !hasExactKeys(value, keys) || value.schema_version !== "1.0" ||
      value.profile_checksum !== VIDEO_NORMALIZATION_PROFILE_V1.profile_checksum || !isPreset(value.selected_preset) ||
      typeof value.implementation_id !== "string" || value.implementation_id.length === 0 || value.implementation_id.length > 128 ||
      typeof value.implementation_version !== "string" || value.implementation_version.length === 0 || value.implementation_version.length > 64 ||
      !isRecord(value.source) || !hasExactKeys(value.source, ["original_name", "size_bytes", "last_modified_ms", "declared_source_checksum"]) ||
      typeof value.source.original_name !== "string" || value.source.original_name.length === 0 || value.source.original_name.length > 255 ||
      !isPositiveInteger(value.source.size_bytes) || !isNonnegativeInteger(value.source.last_modified_ms) ||
      !isChecksum(value.source.declared_source_checksum) || !isRecord(value.prepared_file) ||
      !hasExactKeys(value.prepared_file, ["content_type", "size_bytes", "checksum"]) || value.prepared_file.content_type !== "video/mp4" ||
      !isPositiveInteger(value.prepared_file.size_bytes) || !isChecksum(value.prepared_file.checksum) ||
      !parseVideoStream(value.source_video) || !parseVideoStream(value.prepared_video) ||
      !isRecord(value.pixel_transform) || !hasExactKeys(value.pixel_transform, ["matrix"]) ||
      !Array.isArray(value.pixel_transform.matrix) || value.pixel_transform.matrix.length !== 3 ||
      !isRecord(value.frame_map) || !hasExactKeys(value.frame_map, ["format", "checksum", "size_bytes", "entry_count", "source_frame_count"]) ||
      value.frame_map.format !== "r2s_video_frame_map_jsonl_v1" || !isChecksum(value.frame_map.checksum) ||
      !isPositiveInteger(value.frame_map.size_bytes) || value.frame_map.size_bytes > VIDEO_NORMALIZATION_PROFILE_V1.max_frame_map_bytes ||
      !isPositiveInteger(value.frame_map.entry_count) || !isPositiveInteger(value.frame_map.source_frame_count) ||
      !["source_has_no_audio", "preserved", "omitted_with_user_consent"].includes(String(value.audio_disposition)) ||
      !isChecksum(value.preparation_checksum)) {
    throw new Error("Video preparation manifest is not valid");
  }
  const matrix = value.pixel_transform.matrix;
  if (!matrix.every((row) => Array.isArray(row) && row.length === 3 && row.every((item) => typeof item === "number" && Number.isFinite(item)))) {
    throw new Error("Video pixel transform matrix is not valid");
  }
  const affineRow = matrix[2] as number[];
  if (affineRow[0] !== 0 || affineRow[1] !== 0 || affineRow[2] !== 1) throw new Error("Video pixel transform must be affine");
  const first = matrix[0] as number[];
  const second = matrix[1] as number[];
  if (Math.abs(first[0] * second[1] - first[1] * second[0]) < 1e-12) throw new Error("Video pixel transform is singular");

  const source = value.source_video;
  const prepared = value.prepared_video;
  const selected = VIDEO_NORMALIZATION_PROFILE_V1.presets.find((item) => item.preset === value.selected_preset);
  const outputLong = Math.max(prepared.display_width, prepared.display_height);
  const outputShort = Math.min(prepared.display_width, prepared.display_height);
  if (!selected || value.frame_map.entry_count !== prepared.frame_count ||
      value.frame_map.source_frame_count !== source.frame_count || prepared.rotation_degrees !== 0 ||
      prepared.sample_aspect_ratio.numerator !== prepared.sample_aspect_ratio.denominator ||
      prepared.coded_width !== prepared.display_width || prepared.coded_height !== prepared.display_height ||
      outputLong > selected.max_long_edge_px || outputShort > selected.max_short_edge_px ||
      prepared.display_width > source.display_width || prepared.display_height > source.display_height ||
      !isAvcCodec(prepared.codec) || !preservesSdrColorMetadata(source.color, prepared.color) ||
      isHdrTransfer(source.color?.transfer ?? null)) {
    throw new Error("Video preparation metadata and frame map disagree with the active profile");
  }
  const audio = value.audio_disposition;
  if ((audio === "source_has_no_audio" && (source.audio_track_count !== 0 || prepared.audio_track_count !== 0)) ||
      (audio === "preserved" && (source.audio_track_count === 0 || prepared.audio_track_count !== source.audio_track_count)) ||
      (audio === "omitted_with_user_consent" && (source.audio_track_count === 0 || prepared.audio_track_count !== 0))) {
    throw new Error("Video audio disposition does not match stream metadata");
  }
  return value as unknown as ClientVideoPreparationManifest;
}

function canonicalJson(value: unknown, floatingPoint = false): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Video preparation checksum cannot include non-finite numbers");
    if (floatingPoint) return pythonFloatString(value);
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item, floatingPoint)).join(",")}]`;
  if (isRecord(value)) {
    const members = Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${canonicalJson(value[key], floatingPoint || key === "matrix")}`);
    return `{${members.join(",")}}`;
  }
  throw new Error("Video preparation checksum only supports JSON values");
}

function pythonFloatString(value: number): string {
  if (Object.is(value, -0)) return "-0.0";
  const [mantissa, exponentText] = value.toExponential().split("e");
  const exponent = Number(exponentText);
  if (exponent < -4 || exponent >= 16) {
    const sign = exponent < 0 ? "-" : "+";
    return `${mantissa}e${sign}${String(Math.abs(exponent)).padStart(2, "0")}`;
  }
  const negative = mantissa.startsWith("-");
  const digits = mantissa.replace("-", "").replace(".", "");
  const decimalPosition = 1 + exponent;
  const fixed = decimalPosition <= 0
    ? `0.${"0".repeat(-decimalPosition)}${digits}`
    : decimalPosition >= digits.length
      ? `${digits}${"0".repeat(decimalPosition - digits.length)}.0`
      : `${digits.slice(0, decimalPosition)}.${digits.slice(decimalPosition)}`;
  return negative ? `-${fixed}` : fixed;
}

/** Build the same sorted-key SHA-256 logical identity used by the Python contract. */
export async function calculateVideoPreparationChecksum(
  manifest: Omit<ClientVideoPreparationManifest, "preparation_checksum">,
): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error("Web Crypto is required to checksum video preparation metadata");
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalJson(manifest)));
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `sha256:${hex}`;
}

export async function verifyVideoPreparationChecksum(manifest: ClientVideoPreparationManifest): Promise<void> {
  const { preparation_checksum: expected, ...payload } = manifest;
  const actual = await calculateVideoPreparationChecksum(payload);
  if (actual !== expected) throw new Error("Video preparation checksum does not match canonical content");
}
