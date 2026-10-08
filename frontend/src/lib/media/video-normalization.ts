import {
  calculateVideoPreparationChecksum,
  parseVideoPreparationManifest,
  verifyVideoPreparationChecksum,
  VIDEO_NORMALIZATION_PROFILE_V1,
  type ClientVideoPreparationManifest,
  type VideoResolutionPreset,
} from "@/lib/contracts/videoPreparation";
import {
  normalizedVideoFileName,
  VIDEO_NORMALIZER_IMPLEMENTATION_ID,
  VIDEO_NORMALIZER_IMPLEMENTATION_VERSION,
  VideoPreparationError,
  type VideoPreparationPhase,
  type VideoPreparationWorkerResponse,
  type VideoPreparationWorkerResult,
} from "./video-normalization-core";

export interface VideoPreparationProgress {
  phase: VideoPreparationPhase;
  progress: number;
}

export interface VideoPreparationRequest {
  source: File;
  preset?: VideoResolutionPreset;
  /** True only after the user has explicitly chosen to omit unsupported audio tracks. */
  omitAudioWithConsent?: boolean;
  signal?: AbortSignal;
  onProgress?: (progress: VideoPreparationProgress) => void;
}

export interface VideoPreparedArtifact {
  file: File;
  frameMapFile: File;
  manifest: ClientVideoPreparationManifest;
  dispose: () => Promise<void>;
}

interface WorkerStartMessage {
  type: "start";
  request_id: string;
  source_file: File;
  preset: VideoResolutionPreset;
  omit_audio_with_consent: boolean;
  output_file_name: string;
  frame_map_file_name: string;
  selection_file_name: string;
}

interface WorkerCancelMessage {
  type: "cancel";
  request_id: string;
}

type WorkerRequest = WorkerStartMessage | WorkerCancelMessage;

export interface VideoNormalizerWorkerPort {
  onmessage: ((event: MessageEvent<VideoPreparationWorkerResponse>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  onmessageerror: ((event: MessageEvent) => void) | null;
  postMessage(message: WorkerRequest): void;
  terminate(): void;
}

export interface VideoNormalizerDependencies {
  createWorker?: () => VideoNormalizerWorkerPort;
  openDirectory?: () => Promise<FileSystemDirectoryHandle>;
}

function createWorker(): VideoNormalizerWorkerPort {
  return new Worker(new URL("./video-normalization.worker.ts", import.meta.url), {
    type: "module",
    name: "real2sim-video-normalizer",
  });
}

function openOriginDirectory(): Promise<FileSystemDirectoryHandle> {
  if (!globalThis.navigator?.storage?.getDirectory) {
    throw new VideoPreparationError("storage_unavailable", "This browser cannot store a prepared video safely on disk.");
  }
  return globalThis.navigator.storage.getDirectory();
}

function randomName(suffix: string): string {
  if (!globalThis.crypto?.randomUUID) {
    throw new VideoPreparationError("storage_unavailable", "A secure browser context is required to prepare videos.");
  }
  return `real2sim-video-${globalThis.crypto.randomUUID()}${suffix}`;
}

function removeMissingEntry(error: unknown): boolean {
  return error instanceof DOMException && error.name === "NotFoundError";
}

async function removeFiles(directory: FileSystemDirectoryHandle, names: string[]): Promise<void> {
  const results = await Promise.allSettled(names.map((name) => directory.removeEntry(name)));
  const failures = results.flatMap((result) => {
    if (result.status === "fulfilled" || removeMissingEntry(result.reason)) return [];
    return [result.reason];
  });
  if (failures.length > 0) throw new AggregateError(failures, "Temporary video files could not be removed.");
}

function runWorker(
  worker: VideoNormalizerWorkerPort,
  message: WorkerStartMessage,
  signal: AbortSignal | undefined,
  onProgress: ((progress: VideoPreparationProgress) => void) | undefined,
): Promise<VideoPreparationWorkerResult> {
  return new Promise((resolve, reject) => {
    let settled = false;
    let cancelTimer: ReturnType<typeof setTimeout> | undefined;

    const finish = (error?: Error, result?: VideoPreparationWorkerResult) => {
      if (settled) return;
      settled = true;
      if (cancelTimer !== undefined) clearTimeout(cancelTimer);
      signal?.removeEventListener("abort", abort);
      worker.onmessage = null;
      worker.onerror = null;
      worker.onmessageerror = null;
      worker.terminate();
      if (error) reject(error);
      else if (result) resolve(result);
      else reject(new VideoPreparationError("media_processing_failed", "The local video worker returned no result."));
    };

    const abort = () => {
      if (settled) return;
      worker.postMessage({ type: "cancel", request_id: message.request_id });
      cancelTimer = setTimeout(() => {
        finish(new VideoPreparationError("cancelled", "Video preparation was cancelled; no upload was started."));
      }, 5_000);
    };

    worker.onmessage = (event) => {
      const response = event.data;
      if (!response || response.request_id !== message.request_id) return;
      if (response.type === "progress") {
        if (Number.isFinite(response.progress)) {
          onProgress?.({ phase: response.phase, progress: Math.max(0, Math.min(1, response.progress)) });
        }
      } else if (response.type === "complete") {
        finish(undefined, response.result);
      } else {
        finish(new VideoPreparationError(response.code, response.message));
      }
    };
    worker.onerror = () => finish(new VideoPreparationError(
      "media_processing_failed",
      "The browser video worker stopped unexpectedly; the original file is unchanged and was not uploaded.",
    ));
    worker.onmessageerror = () => finish(new VideoPreparationError(
      "media_processing_failed",
      "The browser could not read the video worker response; the original file was not uploaded.",
    ));

    if (signal?.aborted) {
      finish(new VideoPreparationError("cancelled", "Video preparation was cancelled; no upload was started."));
      return;
    }
    signal?.addEventListener("abort", abort, { once: true });
    worker.postMessage(message);
  });
}

export async function prepareVideoForUpload(
  request: VideoPreparationRequest,
  dependencies: VideoNormalizerDependencies = {},
): Promise<VideoPreparedArtifact> {
  const preset = request.preset ?? VIDEO_NORMALIZATION_PROFILE_V1.default_preset;
  if (!VIDEO_NORMALIZATION_PROFILE_V1.presets.some((item) => item.preset === preset)) {
    throw new VideoPreparationError("invalid_input", "Choose one of the supported video resolution presets.");
  }
  if (request.source.size <= 0 || !request.source.name) {
    throw new VideoPreparationError("invalid_input", "Choose a non-empty video file before preparing it.");
  }
  if (request.signal?.aborted) {
    throw new VideoPreparationError("cancelled", "Video preparation was cancelled; no upload was started.");
  }

  const directoryProvider = dependencies.openDirectory ?? openOriginDirectory;
  const directory = await directoryProvider();
  const outputFileName = randomName(".mp4");
  const frameMapFileName = randomName(".jsonl");
  const selectionFileName = randomName(".frames");
  const requestId = globalThis.crypto.randomUUID();
  const temporaryNames = [outputFileName, frameMapFileName, selectionFileName];
  const workerFactory = dependencies.createWorker ?? createWorker;
  const worker = workerFactory();

  try {
    const result = await runWorker(worker, {
      type: "start",
      request_id: requestId,
      source_file: request.source,
      preset,
      omit_audio_with_consent: request.omitAudioWithConsent ?? false,
      output_file_name: outputFileName,
      frame_map_file_name: frameMapFileName,
      selection_file_name: selectionFileName,
    }, request.signal, request.onProgress);
    if (result.output_file_name !== outputFileName || result.frame_map_file_name !== frameMapFileName) {
      throw new VideoPreparationError("verification_failed", "The video worker returned an unexpected temporary file.");
    }

    const [preparedHandle, mapHandle] = await Promise.all([
      directory.getFileHandle(outputFileName),
      directory.getFileHandle(frameMapFileName),
    ]);
    const [preparedBlob, mapBlob] = await Promise.all([preparedHandle.getFile(), mapHandle.getFile()]);
    if (preparedBlob.size !== result.prepared_size_bytes || mapBlob.size !== result.frame_map.size_bytes) {
      throw new VideoPreparationError("verification_failed", "Prepared media size does not match the completed worker result.");
    }

    const preparedFile = new File([preparedBlob], normalizedVideoFileName(request.source.name), {
      type: "video/mp4",
      lastModified: Date.now(),
    });
    const frameMapFile = new File([mapBlob], "video-frame-map.jsonl", {
      type: "application/x-ndjson",
      lastModified: Date.now(),
    });
    const payload: Omit<ClientVideoPreparationManifest, "preparation_checksum"> = {
      schema_version: "1.0",
      profile_checksum: VIDEO_NORMALIZATION_PROFILE_V1.profile_checksum,
      selected_preset: preset,
      implementation_id: VIDEO_NORMALIZER_IMPLEMENTATION_ID,
      implementation_version: VIDEO_NORMALIZER_IMPLEMENTATION_VERSION,
      source: {
        original_name: request.source.name,
        size_bytes: request.source.size,
        last_modified_ms: Math.max(0, Math.trunc(request.source.lastModified)),
        declared_source_checksum: result.source_checksum,
      },
      prepared_file: {
        content_type: "video/mp4",
        size_bytes: preparedFile.size,
        checksum: result.prepared_checksum,
      },
      source_video: result.source_video,
      prepared_video: result.prepared_video,
      pixel_transform: result.pixel_transform,
      frame_map: result.frame_map,
      audio_disposition: result.audio_disposition,
    };
    const preparationChecksum = await calculateVideoPreparationChecksum(payload);
    const manifest = parseVideoPreparationManifest({ ...payload, preparation_checksum: preparationChecksum });
    await verifyVideoPreparationChecksum(manifest);

    return {
      file: preparedFile,
      frameMapFile,
      manifest,
      dispose: () => removeFiles(directory, temporaryNames),
    };
  } catch (error) {
    try {
      await removeFiles(directory, temporaryNames);
    } catch (cleanupError) {
      const message = error instanceof VideoPreparationError
        ? `${error.message} Temporary video files could not be removed.`
        : "Video preparation failed and temporary files could not be removed.";
      throw new AggregateError([error, cleanupError], message);
    }
    throw error;
  }
}
