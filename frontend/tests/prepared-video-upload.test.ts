import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { uploadPreparedVideo } from "@/lib/api/studio";
import type { UploadRecord } from "@/lib/contracts/studio";
import { parseVideoPreparationManifest } from "@/lib/contracts/videoPreparation";
import type { VideoPreparedArtifact } from "@/lib/media/video-normalization";

function preparedFixture(): VideoPreparedArtifact {
  const manifestPath = resolve(process.cwd(), "../fixtures/contracts/video_preparation_v1.json");
  const fixture = JSON.parse(readFileSync(manifestPath, "utf8")) as { preparation_manifest: unknown };
  const manifest = parseVideoPreparationManifest(fixture.preparation_manifest);
  return {
    file: new File(["x".repeat(manifest.prepared_file.size_bytes)], "prepared.mp4", { type: "video/mp4" }),
    frameMapFile: new File(["x".repeat(manifest.frame_map.size_bytes)], "frames.jsonl", { type: "application/x-ndjson" }),
    manifest,
    dispose: vi.fn().mockResolvedValue(undefined),
  };
}

const uploadRecord: UploadRecord = {
  upload_id: "upload-prepared-1",
  original_name: "prepared.mp4",
  media_type: "video/mp4",
  size_bytes: 45678,
  checksum: "sha256:2222222222222222222222222222222222222222222222222222222222222222",
  artifact_uri: "artifact://uploads/prepared.mp4",
  received_at: "2026-10-08T00:00:00Z",
  project_ids: [],
  input_kind: "rgb_video",
  uploaded_by: { user_id: "user-7", display_name: "Test User", role: "editor" },
};

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    values,
    storage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => void values.set(key, value),
      removeItem: (key: string) => void values.delete(key),
    },
  };
}

describe("uploadPreparedVideo", () => {
  it("uploads prepared bytes, binds the receipt before the frame map, then clears retry keys", async () => {
    const prepared = preparedFixture();
    const storage = memoryStorage();
    const uploadedRecord: UploadRecord = { ...uploadRecord };
    const verifiedRecord: UploadRecord = { ...uploadRecord, video_preparation_status: "verified" };
    const upload = vi.fn().mockReturnValue({ promise: Promise.resolve(uploadedRecord), abort: vi.fn() });
    const apiCall = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("/video-preparation/manifest")) return uploadedRecord;
      if (path.endsWith("/video-preparation/frame-map")) return verifiedRecord;
      throw new Error(`unexpected API call: ${init?.method ?? "GET"} ${path}`);
    });
    const api = <T>(path: string, init?: RequestInit) => apiCall(path, init) as Promise<T>;
    const onUploadedRecord = vi.fn();
    const identity = `user-7:${prepared.manifest.prepared_file.checksum}:${prepared.manifest.preparation_checksum}`;
    const storageKey = `r2s-prepared-upload:v1:${encodeURIComponent(identity)}`;
    const directUploadKey = `r2s-upload:v2:${encodeURIComponent(identity)}`;
    storage.values.set(directUploadKey, uploadRecord.upload_id);

    const handle = uploadPreparedVideo(prepared, {
      accountId: "user-7",
      onProgress: vi.fn(),
      onUploadedRecord,
    }, { upload, api, storage: () => storage.storage });
    const result = await handle.promise;

    expect(result).toEqual(verifiedRecord);
    expect(upload).toHaveBeenCalledWith(prepared.file, expect.any(Function), undefined, {
      resumeIdentity: identity,
      keepResumeKey: true,
    });
    expect(onUploadedRecord).toHaveBeenCalledWith(uploadedRecord);
    expect(apiCall.mock.calls.map(([path, init]) => `${init?.method} ${path}`)).toEqual([
      `PUT /api/v1/uploads/${encodeURIComponent(uploadRecord.upload_id)}/video-preparation/manifest`,
      `PUT /api/v1/uploads/${encodeURIComponent(uploadRecord.upload_id)}/video-preparation/frame-map`,
    ]);
    expect(storage.values.has(storageKey)).toBe(false);
    expect(storage.values.has(directUploadKey)).toBe(false);
  });

  it("rejects a prepared file size mismatch before it opens an upload session", async () => {
    const prepared = preparedFixture();
    const upload = vi.fn();
    const api = vi.fn();
    const storage = memoryStorage();
    const invalid = { ...prepared, file: new File(["short"], "prepared.mp4", { type: "video/mp4" }) };

    await expect(uploadPreparedVideo(invalid, {
      accountId: "user-7",
      onProgress: vi.fn(),
    }, { upload, api, storage: () => storage.storage }).promise).rejects.toThrow(/không khớp với bản gốc/);
    expect(upload).not.toHaveBeenCalled();
    expect(api).not.toHaveBeenCalled();
  });

  it("finds the same-account upload after receipt failure and continues without resending bytes", async () => {
    const prepared = preparedFixture();
    const storage = memoryStorage();
    const identity = `user-7:${prepared.manifest.prepared_file.checksum}:${prepared.manifest.preparation_checksum}`;
    const storageKey = `r2s-prepared-upload:v1:${encodeURIComponent(identity)}`;
    const upload = vi.fn().mockReturnValue({ promise: Promise.resolve(uploadRecord), abort: vi.fn() });
    const firstApiCall = vi.fn(async (path: string, init?: RequestInit) => {
      throw new Error(`temporary manifest outage: ${init?.method} ${path}`);
    });
    const firstApi = <T>(path: string, init?: RequestInit) => firstApiCall(path, init) as Promise<T>;

    await expect(uploadPreparedVideo(prepared, {
      accountId: "user-7",
      onProgress: vi.fn(),
    }, { upload, api: firstApi, storage: () => storage.storage }).promise).rejects.toThrow("temporary manifest outage");
    expect(storage.values.get(storageKey)).toBe(uploadRecord.upload_id);

    const resumedUpload = vi.fn();
    const verifiedRecord = { ...uploadRecord, video_preparation_status: "verified" as const };
    const retryApiCall = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/v1/uploads") return { uploads: [uploadRecord] };
      if (path.endsWith("/video-preparation/manifest")) return uploadRecord;
      if (path.endsWith("/video-preparation/frame-map")) return verifiedRecord;
      throw new Error(`unexpected API call: ${init?.method ?? "GET"} ${path}`);
    });
    const retryApi = <T>(path: string, init?: RequestInit) => retryApiCall(path, init) as Promise<T>;
    const result = await uploadPreparedVideo(prepared, {
      accountId: "user-7",
      onProgress: vi.fn(),
    }, { upload: resumedUpload, api: retryApi, storage: () => storage.storage }).promise;

    expect(result.video_preparation_status).toBe("verified");
    expect(resumedUpload).not.toHaveBeenCalled();
    expect(retryApiCall.mock.calls[0]?.[0]).toBe("/api/v1/uploads");
    expect(storage.values.has(storageKey)).toBe(false);
  });

  it("does not resume an upload record owned by another account", async () => {
    const prepared = preparedFixture();
    const storage = memoryStorage();
    const identity = `user-7:${prepared.manifest.prepared_file.checksum}:${prepared.manifest.preparation_checksum}`;
    const storageKey = `r2s-prepared-upload:v1:${encodeURIComponent(identity)}`;
    storage.values.set(storageKey, "upload-owned-by-another-user");
    const otherOwner: UploadRecord = {
      ...uploadRecord,
      upload_id: "upload-owned-by-another-user",
      uploaded_by: { user_id: "user-8", display_name: "Other User", role: "editor" },
    };
    const upload = vi.fn().mockReturnValue({ promise: Promise.resolve(uploadRecord), abort: vi.fn() });
    const verifiedRecord = { ...uploadRecord, video_preparation_status: "verified" as const };
    const apiCall = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/v1/uploads") return { uploads: [otherOwner] };
      if (path.endsWith("/video-preparation/manifest")) return uploadRecord;
      if (path.endsWith("/video-preparation/frame-map")) return verifiedRecord;
      throw new Error(`unexpected API call: ${init?.method ?? "GET"} ${path}`);
    });
    const api = <T>(path: string, init?: RequestInit) => apiCall(path, init) as Promise<T>;

    await uploadPreparedVideo(prepared, {
      accountId: "user-7",
      onProgress: vi.fn(),
    }, { upload, api, storage: () => storage.storage }).promise;

    expect(upload).toHaveBeenCalledOnce();
    expect(storage.values.has(storageKey)).toBe(false);
  });
});
