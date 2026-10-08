import { describe, expect, it, vi } from "vitest";
import type { VideoPreparationWorkerResponse } from "../src/lib/media/video-normalization-core";
import {
  prepareVideoForUpload,
  type VideoNormalizerWorkerPort,
} from "../src/lib/media/video-normalization";

const digest = (character: string) => `sha256:${character.repeat(64)}`;

type FakeWorkerMessage =
  | { type: "start"; request_id: string; source_file: File; preset: "1080p" | "720p" | "480p";
      omit_audio_with_consent: boolean; output_file_name: string; frame_map_file_name: string; selection_file_name: string }
  | { type: "cancel"; request_id: string };

function streamMetadata(overrides: Partial<{
  codec: string;
  coded_width: number;
  coded_height: number;
  display_width: number;
  display_height: number;
  start_pts: number;
  duration_ticks: number;
  frame_count: number;
}> = {}) {
  return {
    codec: "avc1.640028",
    coded_width: 1280,
    coded_height: 720,
    display_width: 1280,
    display_height: 720,
    sample_aspect_ratio: { numerator: 1, denominator: 1 },
    rotation_degrees: 0 as const,
    start_pts: 90_000,
    duration_ticks: 90_000,
    time_base: { numerator: 1, denominator: 90_000 },
    frame_rate: { numerator: 30, denominator: 1 },
    frame_count: 2,
    color: null,
    audio_track_count: 0,
    ...overrides,
  };
}

class FakeDirectory {
  readonly files = new Map<string, File>();
  readonly removed: string[] = [];

  async getFileHandle(name: string) {
    const file = this.files.get(name);
    if (!file) throw new DOMException("No file", "NotFoundError");
    return { getFile: async () => file } as unknown as FileSystemFileHandle;
  }

  async removeEntry(name: string) {
    this.removed.push(name);
    if (!this.files.delete(name)) throw new DOMException("No file", "NotFoundError");
  }
}

class FakeWorker implements VideoNormalizerWorkerPort {
  onmessage: ((event: MessageEvent<VideoPreparationWorkerResponse>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  onmessageerror: ((event: MessageEvent) => void) | null = null;
  terminated = false;

  constructor(private readonly directory: FakeDirectory, private readonly complete: boolean) {}

  postMessage(message: FakeWorkerMessage) {
    if (message.type === "cancel") {
      this.onmessage?.({ data: {
        type: "failure",
        request_id: message.request_id,
        code: "cancelled",
        message: "Video preparation was cancelled; no upload was started.",
      } } as MessageEvent<VideoPreparationWorkerResponse>);
      return;
    }
    if (!this.complete) return;
    const prepared = new File(["prepared"], "prepared.mp4", { type: "video/mp4" });
    const map = new File(["{}\n"], "map.jsonl", { type: "application/x-ndjson" });
    const outputName = String(message.output_file_name);
    const mapName = String(message.frame_map_file_name);
    this.directory.files.set(outputName, prepared);
    this.directory.files.set(mapName, map);
    this.onmessage?.({ data: {
      type: "complete",
      request_id: message.request_id,
      result: {
        source_checksum: digest("1"),
        prepared_checksum: digest("2"),
        prepared_size_bytes: prepared.size,
        source_video: streamMetadata({
          codec: "hevc",
          coded_width: 1920,
          coded_height: 1080,
          display_width: 1920,
          display_height: 1080,
        }),
        prepared_video: streamMetadata(),
        pixel_transform: { matrix: [[2 / 3, 0, -1 / 6], [0, 2 / 3, -1 / 6], [0, 0, 1]] },
        frame_map: {
          format: "r2s_video_frame_map_jsonl_v1",
          checksum: digest("3"),
          size_bytes: map.size,
          entry_count: 2,
          source_frame_count: 2,
        },
        audio_disposition: "source_has_no_audio",
        output_file_name: outputName,
        frame_map_file_name: mapName,
      },
    } } as MessageEvent<VideoPreparationWorkerResponse>);
  }

  terminate() {
    this.terminated = true;
  }
}

describe("local video preparation service lifecycle", () => {
  it("returns only the finalized prepared file, verifies the contract, and owns temporary-file cleanup", async () => {
    const directory = new FakeDirectory();
    const worker = new FakeWorker(directory, true);
    const source = new File(["original"], "capture.mov", { type: "video/quicktime", lastModified: 123 });
    const onProgress = vi.fn();

    const prepared = await prepareVideoForUpload({ source, onProgress }, {
      createWorker: () => worker,
      openDirectory: async () => directory as unknown as FileSystemDirectoryHandle,
    });

    expect(prepared.file.name).toBe("capture.prepared.mp4");
    expect(prepared.file.type).toBe("video/mp4");
    expect(prepared.manifest.selected_preset).toBe("720p");
    expect(prepared.manifest.source.size_bytes).toBe(source.size);
    expect(prepared.manifest.source_video.codec).toBe("hevc");
    expect(onProgress).toHaveBeenCalledTimes(0);
    expect(worker.terminated).toBe(true);

    await prepared.dispose();
    expect(directory.files.size).toBe(0);
    expect(directory.removed).toHaveLength(3);
  });

  it("requests worker cancellation, terminates it, and removes any partial output", async () => {
    const directory = new FakeDirectory();
    const worker = new FakeWorker(directory, false);
    const source = new File(["original"], "capture.mp4", { type: "video/mp4" });
    const controller = new AbortController();
    const pending = prepareVideoForUpload({ source, signal: controller.signal }, {
      createWorker: () => worker,
      openDirectory: async () => directory as unknown as FileSystemDirectoryHandle,
    });
    await Promise.resolve();
    controller.abort();

    await expect(pending).rejects.toMatchObject({ code: "cancelled" });
    expect(worker.terminated).toBe(true);
    expect(directory.removed).toHaveLength(3);
    expect(directory.files.size).toBe(0);
  });
});
