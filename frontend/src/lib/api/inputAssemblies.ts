import { apiFetch, ApiError } from "@/lib/api/client";
import { directUpload, xhrPutPart } from "@/lib/api/directUpload";
import type { JobManifest, ProjectResponse } from "@/lib/contracts/api";
import type {
  AssemblyUploadResponse,
  InputAssemblySnapshot,
  InputResolutionReport,
  InputAssemblyWriteRequest,
} from "@/lib/contracts/inputAssembly";
import type { ImportedScene, SourceRightsAttestation } from "@/lib/contracts/studio";
import { formatBytes } from "@/lib/format";

const API = "/api/v1";

export interface InputAssemblyRunRequest {
  revision: number;
  resolution_checksum: string;
  candidate_id: string;
  name: string;
  attestation: SourceRightsAttestation;
  processing?: Record<string, number | string>;
  /** Tự động che khuôn mặt/biển số trước khi dựng 3D; chỉ gửi khi server báo `anonymize_available`. */
  anonymize?: boolean;
}

export interface InputAssemblyRunResponse {
  project: ProjectResponse;
  job: JobManifest;
}

export interface InputAssemblyImportResponse {
  imported_scene: ImportedScene;
  intent_checksum: string;
}

export interface AssemblyFileUploadHandle {
  promise: Promise<AssemblyUploadResponse>;
  abort: () => void;
}

export function getStagedInputUpload(uploadId: string, signal?: AbortSignal): Promise<AssemblyUploadResponse> {
  return apiFetch<AssemblyUploadResponse>(`${API}/input-assemblies/uploads/${encodeURIComponent(uploadId)}`, { signal });
}

export function stageExistingInputUpload(uploadId: string, signal?: AbortSignal): Promise<AssemblyUploadResponse> {
  return apiFetch<AssemblyUploadResponse>(`${API}/input-assemblies/uploads/${encodeURIComponent(uploadId)}/stage`, {
    method: "POST",
    signal,
  });
}

/** Upload and probe a non-video input with the grouped-upload purpose. */
export function uploadAssemblyFile(
  file: File,
  accountId: string,
  onProgress: (fraction: number) => void,
): AssemblyFileUploadHandle {
  const controller = new AbortController();
  let request: XMLHttpRequest | null = null;
  const promise = (async () => {
    const config = await apiFetch<{ direct: boolean; max_bytes: number }>(`${API}/uploads/config`, {
      signal: controller.signal,
    });
    if (file.size > config.max_bytes) throw new ApiError(413, `File vượt giới hạn ${formatBytes(config.max_bytes)}`);
    if (controller.signal.aborted) throw new ApiError(499, "Đã hủy tải lên");

    if (config.direct) {
      const state = await directUpload(
        file,
        {
          onProgress,
          signal: controller.signal,
          purpose: "input_assembly",
          resumeIdentity: `${accountId}:${file.name}:${file.size}:${file.lastModified}`,
        },
        {
          api: apiFetch,
          putPart: xhrPutPart,
          sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
          storage: browserStorage(),
        },
      );
      if (controller.signal.aborted) throw new ApiError(499, "Đã hủy tải lên");
      return getStagedInputUpload(state.upload_id);
    }

    return new Promise<AssemblyUploadResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      request = xhr;
      xhr.open("POST", `${API}/input-assemblies/uploads?filename=${encodeURIComponent(file.name)}`);
      xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText) as AssemblyUploadResponse);
          } catch {
            reject(new ApiError(xhr.status, "Máy chủ trả về kết quả upload không hợp lệ"));
          }
          return;
        }
        let detail = xhr.responseText || `HTTP ${xhr.status}`;
        try {
          const parsed = JSON.parse(xhr.responseText) as { detail?: unknown };
          if (typeof parsed.detail === "string") detail = parsed.detail;
        } catch {
          // Giữ nội dung thô nếu server không trả JSON.
        }
        reject(new ApiError(xhr.status, detail));
      };
      xhr.onerror = () => reject(new ApiError(0, "Mất kết nối khi đang tải input lên"));
      xhr.onabort = () => reject(new ApiError(499, "Đã hủy tải lên"));
      xhr.send(file);
    });
  })();
  return {
    promise,
    abort: () => {
      controller.abort();
      request?.abort();
    },
  };
}

export function createInputAssembly(request: InputAssemblyWriteRequest): Promise<InputAssemblySnapshot> {
  return apiFetch<InputAssemblySnapshot>(`${API}/input-assemblies`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function reviseInputAssembly(
  assemblyId: string,
  expectedRevision: number,
  request: InputAssemblyWriteRequest,
): Promise<InputAssemblySnapshot> {
  return apiFetch<InputAssemblySnapshot>(`${API}/input-assemblies/${encodeURIComponent(assemblyId)}`, {
    method: "PUT",
    body: JSON.stringify({ ...request, expected_revision: expectedRevision }),
  });
}

export function resolveInputAssembly(assemblyId: string, revision: number): Promise<{ report: InputResolutionReport }> {
  return apiFetch<{ report: InputResolutionReport }>(`${API}/input-assemblies/${encodeURIComponent(assemblyId)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ revision }),
  });
}

export function runInputAssembly(
  assemblyId: string,
  request: InputAssemblyRunRequest,
  idempotencyKey = globalThis.crypto.randomUUID(),
): Promise<InputAssemblyRunResponse> {
  return apiFetch<InputAssemblyRunResponse>(`${API}/input-assemblies/${encodeURIComponent(assemblyId)}/run`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(request),
  });
}

export function importGaussianFromAssembly(
  assemblyId: string,
  request: Omit<InputAssemblyRunRequest, "attestation" | "processing">,
  idempotencyKey = globalThis.crypto.randomUUID(),
): Promise<InputAssemblyImportResponse> {
  return apiFetch<InputAssemblyImportResponse>(`${API}/input-assemblies/${encodeURIComponent(assemblyId)}/import`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(request),
  });
}

function browserStorage(): Pick<Storage, "getItem" | "setItem" | "removeItem"> | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}
