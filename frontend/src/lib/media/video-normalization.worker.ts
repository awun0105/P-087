import { sha256 } from "@noble/hashes/sha2.js";
import {
  ALL_FORMATS,
  BlobSource,
  Conversion,
  Input,
  Mp4OutputFormat,
  Output,
  Quality,
  StreamTarget,
  VideoSampleSink,
  type InputAudioTrack,
  type InputVideoTrack,
  type StreamTargetChunk,
} from "mediabunny";
import {
  fitVideoDimensions,
  VIDEO_NORMALIZATION_PROFILE_V1,
  type VideoColorMetadata,
  type VideoResolutionPreset,
  type VideoStreamMetadata,
} from "@/lib/contracts/videoPreparation";
import {
  createVideoPixelTransform,
  FRAME_MAP_ROW_BYTES,
  MAX_DECODED_VIDEO_PIXELS,
  MAX_VIDEO_DURATION_SECONDS,
  PresentationFrameSelector,
  presetBitrate,
  simplifyPositiveRational,
  STORAGE_RESERVE_BYTES,
  timestampToTicks,
  timeBaseForResolution,
  validateRightAngleTransformation,
  VideoPreparationError,
  type VideoPreparationErrorCode,
  type VideoPreparationPhase,
  type VideoPreparationWorkerResponse,
  type VideoPreparationWorkerResult,
} from "./video-normalization-core";

interface VideoPreparationStart {
  type: "start";
  request_id: string;
  source_file: File;
  preset: VideoResolutionPreset;
  omit_audio_with_consent: boolean;
  output_file_name: string;
  frame_map_file_name: string;
  selection_file_name: string;
}

interface VideoPreparationCancel {
  type: "cancel";
  request_id: string;
}

type WorkerRequest = VideoPreparationStart | VideoPreparationCancel;

const workerScope = globalThis as unknown as {
  navigator: Navigator & { storage: StorageManager };
  isSecureContext: boolean;
  postMessage(message: VideoPreparationWorkerResponse): void;
  addEventListener(type: "message", listener: (event: MessageEvent<WorkerRequest>) => void): void;
};
let activeRequestId: string | null = null;
let activeConversion: Conversion | null = null;
let cancelled = false;

function postProgress(requestId: string, phase: VideoPreparationPhase, progress: number): void {
  const message: VideoPreparationWorkerResponse = {
    type: "progress",
    request_id: requestId,
    phase,
    progress: Math.max(0, Math.min(1, progress)),
  };
  workerScope.postMessage(message);
}

function failIfCancelled(): void {
  if (cancelled) throw new VideoPreparationError("cancelled", "Video preparation was cancelled; no upload was started.");
}

function colorMetadata(color: VideoColorSpaceInit): VideoColorMetadata | null {
  const value: VideoColorMetadata = {
    primaries: color.primaries ?? null,
    transfer: color.transfer ?? null,
    matrix: color.matrix ?? null,
    range: color.fullRange === true ? "full" : color.fullRange === false ? "limited" : null,
  };
  return Object.values(value).every((part) => part === null) ? null : value;
}

function sameColor(left: VideoColorMetadata | null, right: VideoColorMetadata | null): boolean {
  return left === null ? right === null : right !== null &&
    left.primaries === right.primaries && left.transfer === right.transfer &&
    left.matrix === right.matrix && left.range === right.range;
}

function safeCodec(value: string | number | Uint8Array | null): string {
  if (value === null) return "unknown";
  if (typeof value === "string" || typeof value === "number") return String(value).slice(0, 128);
  return Array.from(value).map((byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 128) || "unknown";
}

function rationalRate(timeResolution: number, frameDelta: number | null, constant: boolean): { numerator: number; denominator: number } | null {
  if (!constant || frameDelta === null || frameDelta <= 0) return null;
  return simplifyPositiveRational(timeResolution, frameDelta);
}

class FrameRateCounter {
  private previous: number | null = null;
  private delta: number | null = null;
  private constant = true;

  add(pts: number): void {
    if (this.previous !== null) {
      const nextDelta = pts - this.previous;
      if (nextDelta <= 0) throw new VideoPreparationError("unsupported_media", "Video frame timestamps are not strictly increasing.");
      if (this.delta === null) this.delta = nextDelta;
      else if (this.delta !== nextDelta) this.constant = false;
    }
    this.previous = pts;
  }

  value(timeResolution: number): { numerator: number; denominator: number } | null {
    return rationalRate(timeResolution, this.delta, this.constant);
  }
}

async function hashBlob(blob: Blob): Promise<string> {
  const hash = sha256.create();
  const reader = blob.stream().getReader();
  try {
    while (true) {
      failIfCancelled();
      const { done, value } = await reader.read();
      if (done) break;
      hash.update(value);
    }
  } finally {
    reader.releaseLock();
  }
  return `sha256:${Array.from(hash.digest(), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

async function outputFileLimit(durationSeconds: number, audioTracks: InputAudioTrack[], preset: VideoResolutionPreset): Promise<number> {
  const storage = workerScope.navigator.storage;
  if (!storage?.estimate || !storage.getDirectory) {
    throw new VideoPreparationError("storage_unavailable", "This browser does not expose bounded local video storage.");
  }
  const estimate = await storage.estimate();
  if (!Number.isFinite(estimate.quota) || !Number.isFinite(estimate.usage)) {
    throw new VideoPreparationError("storage_unavailable", "The browser could not estimate available local storage.");
  }
  const availableBytes = Math.max(0, (estimate.quota ?? 0) - (estimate.usage ?? 0));
  const reservedBytes = STORAGE_RESERVE_BYTES + VIDEO_NORMALIZATION_PROFILE_V1.max_frame_map_bytes + 8 * 1024 * 1024;
  const remaining = availableBytes - reservedBytes;
  const audioBitrate = (await Promise.all(audioTracks.map(async (track) =>
    Math.max(256_000, (await track.getAverageBitrate()) ?? 512_000),
  ))).reduce((sum, bitrate) => sum + bitrate, 0);
  const estimatedOutputBytes = Math.ceil(durationSeconds * (presetBitrate(preset) + audioBitrate) / 8 * 1.5);
  if (remaining < estimatedOutputBytes) {
    throw new VideoPreparationError(
      "storage_insufficient",
      "There is not enough browser storage for the estimated prepared video and frame map. Free local storage and retry.",
    );
  }
  return remaining;
}

async function createBoundedTarget(
  fileHandle: FileSystemFileHandle,
  maxBytes: number,
): Promise<StreamTarget> {
  const fileWriter = await fileHandle.createWritable({ keepExistingData: false });
  const bounded = new WritableStream<StreamTargetChunk>({
    async write(chunk) {
      if (chunk.position < 0 || chunk.position + chunk.data.byteLength > maxBytes) {
        throw new VideoPreparationError("storage_insufficient", "The prepared video exceeded the available local storage budget.");
      }
      await fileWriter.write(chunk);
    },
    close: () => fileWriter.close(),
    abort: (reason) => fileWriter.abort(reason),
  }, { highWaterMark: 1 });
  return new StreamTarget(bounded);
}

class SelectionRowsWriter {
  private readonly bytes = new Uint8Array(FRAME_MAP_ROW_BYTES * 1024);
  private readonly view = new DataView(this.bytes.buffer);
  private used = 0;

  constructor(private readonly writer: FileSystemWritableFileStream) {}

  async write(sourceFrameIndex: number, sourcePts: number): Promise<void> {
    this.view.setBigUint64(this.used, BigInt(sourceFrameIndex), false);
    this.view.setBigInt64(this.used + 8, BigInt(sourcePts), false);
    this.used += FRAME_MAP_ROW_BYTES;
    if (this.used === this.bytes.byteLength) await this.flush();
  }

  async flush(): Promise<void> {
    if (this.used === 0) return;
    await this.writer.write(this.bytes.slice(0, this.used));
    this.used = 0;
  }
}

class SelectionRowsReader {
  private readonly reader: ReadableStreamDefaultReader<Uint8Array>;
  private pending = new Uint8Array(0);
  private ended = false;
  private closed = false;

  constructor(file: File) {
    this.reader = file.stream().getReader();
  }

  async next(): Promise<{ sourceFrameIndex: number; sourcePts: number } | null> {
    while (this.pending.byteLength < FRAME_MAP_ROW_BYTES && !this.ended) {
      const { done, value } = await this.reader.read();
      if (done) {
        this.ended = true;
        break;
      }
      if (!value.byteLength) continue;
      const combined = new Uint8Array(this.pending.byteLength + value.byteLength);
      combined.set(this.pending);
      combined.set(value, this.pending.byteLength);
      this.pending = combined;
    }
    if (this.pending.byteLength === 0 && this.ended) return null;
    if (this.pending.byteLength < FRAME_MAP_ROW_BYTES) {
      throw new VideoPreparationError("verification_failed", "The temporary frame mapping is truncated.");
    }
    const row = new DataView(this.pending.buffer, this.pending.byteOffset, FRAME_MAP_ROW_BYTES);
    const sourceFrameIndex = Number(row.getBigUint64(0, false));
    const sourcePts = Number(row.getBigInt64(8, false));
    this.pending = this.pending.subarray(FRAME_MAP_ROW_BYTES);
    if (!Number.isSafeInteger(sourceFrameIndex) || !Number.isSafeInteger(sourcePts)) {
      throw new VideoPreparationError("verification_failed", "A temporary frame mapping value is outside the supported range.");
    }
    return { sourceFrameIndex, sourcePts };
  }

  async close(): Promise<void> {
    if (!this.closed) {
      this.closed = true;
      this.reader.releaseLock();
    }
  }
}

async function buildVideoMetadata(
  track: InputVideoTrack,
  frameCount: number,
  audioTrackCount: number,
  frameRate: { numerator: number; denominator: number } | null,
): Promise<VideoStreamMetadata> {
  const [codec, codedWidth, codedHeight, displayWidth, displayHeight, sampleAspect, rotation, startTimestamp, endTimestamp, resolution, color] = await Promise.all([
    track.getCodec(),
    track.getCodedWidth(),
    track.getCodedHeight(),
    track.getDisplayWidth(),
    track.getDisplayHeight(),
    track.getPixelAspectRatio(),
    track.getRotation(),
    track.getFirstTimestamp(),
    track.computeDuration(),
    track.getTimeResolution(),
    track.getColorSpace(),
  ]);
  if (frameCount <= 0 || startTimestamp < 0 || endTimestamp <= startTimestamp) {
    throw new VideoPreparationError("verification_failed", "Video duration or frame count could not be verified.");
  }
  const startPts = timestampToTicks(startTimestamp, resolution);
  const endPts = timestampToTicks(endTimestamp, resolution);
  if (endPts <= startPts) throw new VideoPreparationError("verification_failed", "Video timebase did not preserve a positive duration.");
  const internalCodec = codec ?? await track.getInternalCodecId();
  const pixelAspectRatio = simplifyPositiveRational(sampleAspect.num, sampleAspect.den);
  return {
    codec: safeCodec(internalCodec),
    coded_width: codedWidth,
    coded_height: codedHeight,
    display_width: Math.max(1, Math.round(displayWidth)),
    display_height: Math.max(1, Math.round(displayHeight)),
    sample_aspect_ratio: pixelAspectRatio,
    rotation_degrees: rotation,
    start_pts: startPts,
    duration_ticks: endPts - startPts,
    time_base: timeBaseForResolution(resolution),
    frame_rate: frameRate,
    frame_count: frameCount,
    color: colorMetadata(color),
    audio_track_count: audioTrackCount,
  };
}

function equalFrameTimes(sourcePts: number, sourceResolution: number, outputPts: number, outputResolution: number): boolean {
  const differenceSeconds = Math.abs(sourcePts / sourceResolution - outputPts / outputResolution);
  const toleranceSeconds = 1 / sourceResolution + 1 / outputResolution;
  return differenceSeconds <= toleranceSeconds;
}

async function verifyAudioTracks(sourceTracks: InputAudioTrack[], preparedTracks: InputAudioTrack[]): Promise<void> {
  if (sourceTracks.length !== preparedTracks.length) {
    throw new VideoPreparationError("verification_failed", "Prepared video did not preserve every selected audio track.");
  }
  for (let index = 0; index < sourceTracks.length; index += 1) {
    const source = sourceTracks[index]!;
    const prepared = preparedTracks[index]!;
    const [sourceCodec, preparedCodec, sourceStart, preparedStart, sourceEnd, preparedEnd, sourceResolution, preparedResolution] = await Promise.all([
      source.getCodec(), prepared.getCodec(), source.getFirstTimestamp(), prepared.getFirstTimestamp(),
      source.computeDuration(), prepared.computeDuration(), source.getTimeResolution(), prepared.getTimeResolution(),
    ]);
    const tolerance = 1 / sourceResolution + 1 / preparedResolution;
    if (sourceCodec !== preparedCodec || Math.abs(sourceStart - preparedStart) > tolerance ||
        Math.abs((sourceEnd - sourceStart) - (preparedEnd - preparedStart)) > tolerance) {
      throw new VideoPreparationError("verification_failed", "Prepared video changed an audio codec or audio timeline.");
    }
  }
}

async function verifyAndWriteFrameMap(options: {
  outputInput: Input;
  outputTrack: InputVideoTrack;
  selectionHandle: FileSystemFileHandle;
  mapHandle: FileSystemFileHandle;
  expectedSelectedCount: number;
  expectedSourceCount: number;
  sourceVideo: VideoStreamMetadata;
}): Promise<{ preparedVideo: VideoStreamMetadata; frameMap: VideoPreparationWorkerResult["frame_map"] }> {
  const { outputInput, outputTrack, selectionHandle, mapHandle, expectedSelectedCount, expectedSourceCount, sourceVideo } = options;
  const selectionFile = await selectionHandle.getFile();
  const selections = new SelectionRowsReader(selectionFile);
  const mapWriter = await mapHandle.createWritable({ keepExistingData: false });
  const mapHash = sha256.create();
  const textEncoder = new TextEncoder();
  const mapBuffer = new Uint8Array(64 * 1024);
  let mapBufferUsed = 0;
  let mapBytes = 0;
  let outputFrameCount = 0;
  let priorOutputPts: number | null = null;
  let priorSourceIndex = -1;
  let priorSourcePts: number | null = null;
  const outputResolution = await outputTrack.getTimeResolution();
  const outputFrameRate = new FrameRateCounter();

  const writeMapBytes = async (bytes: Uint8Array): Promise<void> => {
    if (mapBytes + bytes.byteLength > VIDEO_NORMALIZATION_PROFILE_V1.max_frame_map_bytes) {
      throw new VideoPreparationError("frame_map_limit", "The video frame map exceeds the supported 32 MiB limit.");
    }
    mapBytes += bytes.byteLength;
    mapHash.update(bytes);
    if (mapBufferUsed + bytes.byteLength > mapBuffer.byteLength) {
      await mapWriter.write(mapBuffer.slice(0, mapBufferUsed));
      mapBufferUsed = 0;
    }
    mapBuffer.set(bytes, mapBufferUsed);
    mapBufferUsed += bytes.byteLength;
  };

  try {
    const sink = new VideoSampleSink(outputTrack);
    for await (const sample of sink.samples()) {
      try {
        failIfCancelled();
        const outputPts = timestampToTicks(sample.timestamp, outputResolution);
        if (priorOutputPts !== null && outputPts <= priorOutputPts) {
          throw new VideoPreparationError("verification_failed", "Prepared video timestamps are not in presentation order.");
        }
        const sourceRow = await selections.next();
        if (sourceRow === null || sourceRow.sourceFrameIndex >= expectedSourceCount || sourceRow.sourceFrameIndex <= priorSourceIndex ||
            (priorSourcePts !== null && sourceRow.sourcePts <= priorSourcePts) ||
            !equalFrameTimes(sourceRow.sourcePts, sourceVideo.time_base.denominator, outputPts, outputResolution)) {
          throw new VideoPreparationError("verification_failed", "Encoded video presentation timestamps do not match the selected source frames.");
        }
        outputFrameRate.add(outputPts);
        const line = textEncoder.encode(`${JSON.stringify({
          schema_version: "1.0",
          output_frame_index: outputFrameCount,
          output_pts: outputPts,
          source_frame_index: sourceRow.sourceFrameIndex,
          source_pts: sourceRow.sourcePts,
        })}\n`);
        await writeMapBytes(line);
        priorOutputPts = outputPts;
        priorSourceIndex = sourceRow.sourceFrameIndex;
        priorSourcePts = sourceRow.sourcePts;
        outputFrameCount += 1;
      } finally {
        sample.close();
      }
    }
    if (await selections.next() !== null || outputFrameCount !== expectedSelectedCount ||
        expectedSourceCount !== sourceVideo.frame_count || outputFrameCount <= 0) {
      throw new VideoPreparationError("verification_failed", "Prepared frame count does not match its source mapping.");
    }
    await selections.close();
    if (mapBufferUsed > 0) await mapWriter.write(mapBuffer.slice(0, mapBufferUsed));
    await mapWriter.close();

    const preparedVideo = await buildVideoMetadata(
      outputTrack,
      outputFrameCount,
      (await outputInput.getAudioTracks()).length,
      outputFrameRate.value(outputResolution),
    );
    const durationDifference = Math.abs(
      preparedVideo.duration_ticks / preparedVideo.time_base.denominator -
      sourceVideo.duration_ticks / sourceVideo.time_base.denominator,
    );
    if (durationDifference > 1 / VIDEO_NORMALIZATION_PROFILE_V1.max_frame_rate.numerator +
        1 / sourceVideo.time_base.denominator + 1 / preparedVideo.time_base.denominator) {
      throw new VideoPreparationError("verification_failed", "Prepared video duration differs by more than the one-frame tolerance.");
    }
    if (preparedVideo.rotation_degrees !== 0 || preparedVideo.sample_aspect_ratio.numerator !== preparedVideo.sample_aspect_ratio.denominator ||
        preparedVideo.coded_width !== preparedVideo.display_width || preparedVideo.coded_height !== preparedVideo.display_height ||
        !sameColor(sourceVideo.color, preparedVideo.color)) {
      throw new VideoPreparationError("verification_failed", "Rotation, pixel aspect ratio, dimensions, or SDR color metadata was not baked and preserved.");
    }

    return {
      preparedVideo,
      frameMap: {
        format: "r2s_video_frame_map_jsonl_v1",
        checksum: `sha256:${Array.from(mapHash.digest(), (byte) => byte.toString(16).padStart(2, "0")).join("")}`,
        size_bytes: mapBytes,
        entry_count: outputFrameCount,
        source_frame_count: expectedSourceCount,
      },
    };
  } catch (error) {
    await selections.close().catch(() => undefined);
    await mapWriter.abort(error).catch(() => undefined);
    throw error;
  }
}

async function runPreparation(message: VideoPreparationStart): Promise<VideoPreparationWorkerResult> {
  const { request_id: requestId, source_file: sourceFile, preset, output_file_name: outputName,
    frame_map_file_name: mapName, selection_file_name: selectionName } = message;
  if (!workerScope.isSecureContext || !workerScope.navigator?.storage?.getDirectory) {
    throw new VideoPreparationError("storage_unavailable", "Video preparation requires a secure browser context with local disk storage.");
  }
  const directory = await workerScope.navigator.storage.getDirectory();
  let input: Input | null = null;
  let outputInput: Input | null = null;
  let selectionWriter: FileSystemWritableFileStream | null = null;
  let conversion: Conversion | null = null;
  let output: Output | null = null;
  let completed = false;

  try {
    failIfCancelled();
    postProgress(requestId, "probing", 0.02);
    input = new Input({ source: new BlobSource(sourceFile), formats: ALL_FORMATS });
    const tracks = await input.getTracks();
    const videoTracks = tracks.filter((track): track is InputVideoTrack => track.isVideoTrack());
    const audioTracks = tracks.filter((track): track is InputAudioTrack => track.isAudioTrack());
    if (videoTracks.length !== 1 || videoTracks[0] === undefined || tracks.length !== videoTracks.length + audioTracks.length) {
      throw new VideoPreparationError("unsupported_media", "Choose a video with one video track and no subtitle or attachment tracks.");
    }
    const videoTrack = videoTracks[0];
    if (!(await videoTrack.canDecode())) {
      throw new VideoPreparationError("unsupported_codec", "This browser cannot decode the selected video's codec.");
    }
    if (await videoTrack.hasHighDynamicRange()) {
      throw new VideoPreparationError("hdr_unsupported", "HDR video is not supported by the current preparation profile.");
    }

    const [codedWidth, codedHeight, displayWidth, displayHeight, rotation, flip, transformationMatrix, pixelAspect,
      sourceFirstTimestamp, sourceEndTimestamp, sourceTimeResolution] = await Promise.all([
      videoTrack.getCodedWidth(), videoTrack.getCodedHeight(), videoTrack.getDisplayWidth(),
      videoTrack.getDisplayHeight(), videoTrack.getRotation(), videoTrack.getFlip(), videoTrack.getTransformationMatrix(),
      videoTrack.getPixelAspectRatio(), videoTrack.getFirstTimestamp(), videoTrack.computeDuration(),
      videoTrack.getTimeResolution(),
    ]);
    validateRightAngleTransformation(transformationMatrix);
    if (codedWidth * codedHeight > MAX_DECODED_VIDEO_PIXELS) {
      throw new VideoPreparationError("pixel_limit", "This video exceeds the current 12.5 megapixel decode limit.");
    }
    if (sourceFirstTimestamp < 0 || !Number.isFinite(sourceEndTimestamp) || sourceEndTimestamp <= sourceFirstTimestamp) {
      throw new VideoPreparationError("unsupported_media", "Videos with negative or invalid starting timestamps are not supported yet.");
    }
    const durationSeconds = sourceEndTimestamp - sourceFirstTimestamp;
    if (durationSeconds > MAX_VIDEO_DURATION_SECONDS) {
      throw new VideoPreparationError("duration_limit", "This video exceeds the current two-hour preparation limit.");
    }
    const decoderConfig = await videoTrack.getDecoderConfig();
    if (!decoderConfig || typeof VideoDecoder === "undefined" || !(await VideoDecoder.isConfigSupported(decoderConfig)).supported) {
      throw new VideoPreparationError("unsupported_codec", "The browser cannot configure a decoder for this video.");
    }
    if (!message.omit_audio_with_consent && audioTracks.length > 0) {
      const audioStarts = await Promise.all(audioTracks.map((track) => track.getFirstTimestamp()));
      if (audioStarts.some((timestamp) => timestamp < 0)) {
        throw new VideoPreparationError("unsupported_audio", "Audio tracks with negative starting timestamps cannot be preserved by this profile.");
      }
    }

    const dimensions = fitVideoDimensions(Math.max(2, Math.round(displayWidth)),
      Math.max(2, Math.round(displayHeight)), preset);
    const pixelTransform = createVideoPixelTransform({
      codedWidth,
      codedHeight,
      sampleAspectRatio: simplifyPositiveRational(pixelAspect.num, pixelAspect.den),
      rotationDegrees: rotation,
      flipHorizontal: flip,
      outputWidth: dimensions.width,
      outputHeight: dimensions.height,
    });
    const outputLimit = await outputFileLimit(durationSeconds, message.omit_audio_with_consent ? [] : audioTracks, preset);

    if (audioTracks.length > 0 && !message.omit_audio_with_consent) {
      const supportedAudioCodecs = new Mp4OutputFormat().getSupportedAudioCodecs();
      const unsupportedAudio = await Promise.all(audioTracks.map(async (track) => {
        const codec = await track.getCodec();
        return !codec || !supportedAudioCodecs.includes(codec);
      }));
      if (unsupportedAudio.some(Boolean)) {
        throw new VideoPreparationError("audio_omission_required", "One or more audio tracks cannot be preserved in MP4. Choose explicitly to omit audio or use a compatible source.");
      }
    }

    postProgress(requestId, "hashing", 0.05);
    const sourceChecksum = await hashBlob(sourceFile);
    failIfCancelled();

    const outputHandle = await directory.getFileHandle(outputName, { create: true });
    const mapHandle = await directory.getFileHandle(mapName, { create: true });
    const selectionHandle = await directory.getFileHandle(selectionName, { create: true });
    const selectionWritable = await selectionHandle.createWritable({ keepExistingData: false });
    selectionWriter = selectionWritable;
    const selectionRows = new SelectionRowsWriter(selectionWritable);
    const outputTarget = await createBoundedTarget(outputHandle, outputLimit);
    const outputFormat = new Mp4OutputFormat({ fastStart: false });
    output = new Output({ format: outputFormat, target: outputTarget });

    const selector = new PresentationFrameSelector(sourceTimeResolution);
    const sourceFrameRate = new FrameRateCounter();
    let sourceFrameCount = 0;
    let selectedFrameCount = 0;
    let lastSourcePts: number | null = null;
    const audioOmitted = message.omit_audio_with_consent && audioTracks.length > 0;

    conversion = await Conversion.init({
      input,
      output,
      tracks: "all",
      trim: { start: 0 },
      copy: { mode: "forced", shiftTolerance: 0 },
      showWarnings: false,
      video: (track) => track.id === videoTrack.id ? {
        width: dimensions.width,
        height: dimensions.height,
        fit: "fill",
        allowTransformationMetadata: false,
        codec: "avc",
        quality: new Quality({ bitrate: presetBitrate(preset), bitrateMode: "variable" }),
        forceTranscode: true,
        // Do not pass frameRate: MediaBunny's CFR helper duplicates frames to fill VFR gaps.
        // This callback applies the explicit PTS cap and returns null for dropped frames.
        process: async (sample) => {
          failIfCancelled();
          const sourceIndex = sourceFrameCount;
          const sourcePts = timestampToTicks(sample.timestamp, sourceTimeResolution);
          if (lastSourcePts !== null && sourcePts <= lastSourcePts) {
            throw new VideoPreparationError("unsupported_media", "Source presentation timestamps are not strictly increasing.");
          }
          sourceFrameRate.add(sourcePts);
          sourceFrameCount += 1;
          lastSourcePts = sourcePts;
          if (!selector.shouldKeep(sourcePts)) return null;
          await selectionRows.write(sourceIndex, sourcePts);
          selectedFrameCount += 1;
          const progress = Math.min(0.82, 0.08 + Math.max(0, sample.timestamp - sourceFirstTimestamp) / durationSeconds * 0.74);
          postProgress(requestId, "encoding", progress);
          return sample;
        },
      } : { discard: true },
      audio: () => audioOmitted ? { discard: true } : {},
    });
    activeConversion = conversion;

    const unwantedDiscard = conversion.discardedTracks.find((item) =>
      item.reason !== "discarded_by_user" && !(audioOmitted && item.track.isAudioTrack()),
    );
    if (unwantedDiscard?.track.isAudioTrack() && !audioOmitted) {
      throw new VideoPreparationError("unsupported_audio", "An audio track could not be preserved. Choose explicitly to omit audio or use a compatible source.");
    }
    if (unwantedDiscard) {
      throw new VideoPreparationError("unsupported_codec", "The browser cannot encode this video into the required AVC profile.");
    }
    if (!conversion.isValid) throw new VideoPreparationError("unsupported_codec", "The browser could not prepare the required AVC/MP4 output.");

    postProgress(requestId, "encoding", 0.08);
    conversion.onProgress = (progress) => postProgress(requestId, "encoding", 0.08 + Math.max(0, Math.min(1, progress)) * 0.74);
    try {
      await conversion.execute();
    } catch (error) {
      if (cancelled) throw new VideoPreparationError("cancelled", "Video preparation was cancelled; no upload was started.");
      throw new VideoPreparationError("media_processing_failed", `Local decode, encode, or MP4 mux failed: ${String(error).slice(0, 240)}`);
    } finally {
      activeConversion = null;
    }
    failIfCancelled();
    await selectionRows.flush();
    await selectionWritable.close();
    selectionWriter = null;
    if (sourceFrameCount <= 0 || selectedFrameCount <= 0) {
      throw new VideoPreparationError("verification_failed", "The browser did not produce any presentable video frames.");
    }

    const sourceVideo = await buildVideoMetadata(videoTrack, sourceFrameCount, audioTracks.length,
      sourceFrameRate.value(sourceTimeResolution));
    postProgress(requestId, "verifying", 0.84);
    const outputFile = await outputHandle.getFile();
    outputInput = new Input({ source: new BlobSource(outputFile), formats: ALL_FORMATS });
    const preparedTracks = await outputInput.getTracks();
    const preparedVideoTrack = await outputInput.getPrimaryVideoTrack();
    const preparedAudioTracks = preparedTracks.filter((track): track is InputAudioTrack => track.isAudioTrack());
    if (!preparedVideoTrack || preparedTracks.filter((track) => track.isVideoTrack()).length !== 1) {
      throw new VideoPreparationError("verification_failed", "Completed MP4 does not contain exactly one readable video track.");
    }
    if (!audioOmitted) await verifyAudioTracks(audioTracks, preparedAudioTracks);
    else if (preparedAudioTracks.length !== 0) {
      throw new VideoPreparationError("verification_failed", "The explicitly omitted audio tracks are still present in the prepared MP4.");
    }
    if (!await preparedVideoTrack.canDecode()) {
      throw new VideoPreparationError("verification_failed", "The browser cannot read back its prepared AVC output.");
    }

    const { preparedVideo, frameMap } = await verifyAndWriteFrameMap({
      outputInput,
      outputTrack: preparedVideoTrack,
      selectionHandle,
      mapHandle,
      expectedSelectedCount: selectedFrameCount,
      expectedSourceCount: sourceFrameCount,
      sourceVideo,
    });
    const completedFile = await outputHandle.getFile();
    if (completedFile.size <= 0 || completedFile.size > outputLimit) {
      throw new VideoPreparationError("verification_failed", "Prepared MP4 size is outside the verified local storage budget.");
    }

    postProgress(requestId, "verifying", 0.96);
    const [preparedChecksum, mapFile] = await Promise.all([hashBlob(completedFile), mapHandle.getFile()]);
    if (mapFile.size !== frameMap.size_bytes) {
      throw new VideoPreparationError("verification_failed", "The finalized frame map size does not match its descriptor.");
    }
    const result: VideoPreparationWorkerResult = {
      source_checksum: sourceChecksum,
      prepared_checksum: preparedChecksum,
      prepared_size_bytes: completedFile.size,
      source_video: sourceVideo,
      prepared_video: preparedVideo,
      pixel_transform: pixelTransform,
      frame_map: frameMap,
      audio_disposition: audioTracks.length === 0 ? "source_has_no_audio" : audioOmitted ? "omitted_with_user_consent" : "preserved",
      output_file_name: outputName,
      frame_map_file_name: mapName,
    };
    completed = true;
    postProgress(requestId, "verifying", 1);
    return result;
  } finally {
    activeConversion = null;
    input?.dispose();
    outputInput?.dispose();
    if (selectionWriter) await selectionWriter.abort("video preparation ended before frame mapping completed").catch(() => undefined);
    if (!completed) {
      await Promise.allSettled([output?.cancel(), directory.removeEntry(outputName), directory.removeEntry(mapName), directory.removeEntry(selectionName)]);
    } else {
      await directory.removeEntry(selectionName).catch(() => undefined);
    }
  }
}

workerScope.addEventListener("message", (event: MessageEvent<WorkerRequest>) => {
  const message = event.data;
  if (message.type === "cancel") {
    if (activeRequestId === message.request_id) {
      cancelled = true;
      void activeConversion?.cancel();
    }
    return;
  }
  if (activeRequestId !== null) return;
  activeRequestId = message.request_id;
  cancelled = false;
  void runPreparation(message).then((result) => {
    const response: VideoPreparationWorkerResponse = { type: "complete", request_id: message.request_id, result };
    workerScope.postMessage(response);
  }).catch((error: unknown) => {
    const failure = error instanceof VideoPreparationError
      ? error
      : new VideoPreparationError("media_processing_failed", `Local video preparation failed: ${String(error).slice(0, 240)}`);
    const response: VideoPreparationWorkerResponse = {
      type: "failure",
      request_id: message.request_id,
      code: failure.code as VideoPreparationErrorCode,
      message: failure.message,
    };
    workerScope.postMessage(response);
  }).finally(() => {
    activeRequestId = null;
    activeConversion = null;
    cancelled = false;
  });
});
