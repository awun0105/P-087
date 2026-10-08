/**
 * Upload video thẳng từ trình duyệt lên kho file (R2/MinIO) theo từng phần (ADR 0003).
 *
 * - Web UI/API không cõng bytes: API chỉ mở phiên và cấp link PUT có hạn theo nhóm phần.
 * - Chạy song song vài phần, thử lại phần lỗi, xin link mới khi link hết hạn.
 * - Upload legacy nối lại theo tên + kích thước + ngày sửa file. Video chuẩn hóa truyền khóa theo
 *   account + checksum nội dung để tránh nối nhầm phiên khi đổi encoding.
 * - Phần đã nhận được server giữ lại; lần sau chỉ upload các phần còn thiếu.
 * - Server tự ghép và tính checksum; client chỉ poll tới READY/FAILED.
 */

import { ApiError } from "@/lib/api/client";

export interface DirectUploadState {
  upload_id: string;
  original_name: string;
  size_bytes: number;
  part_size: number;
  part_count: number;
  status: "UPLOADING" | "VERIFYING" | "READY" | "FAILED";
  error: string | null;
  uploaded_parts: number[];
}

/** PUT một phần; `onProgress` nhận số byte đã gửi của phần đó. */
export type PutPart = (url: string, body: Blob, onProgress: (loaded: number) => void, signal: AbortSignal) => Promise<void>;

export interface DirectUploadDeps {
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
  putPart: PutPart;
  sleep: (ms: number) => Promise<void>;
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
}

export interface DirectUploadOptions {
  onProgress: (fraction: number) => void;
  onVerifying?: () => void;
  signal: AbortSignal;
  /** Content/account identity for normalized media; omitting keeps the legacy filename key. */
  resumeIdentity?: string;
  /** Keep a READY session until the caller completes a later verification stage. */
  keepResumeKey?: boolean;
  /** Store a verified file in the grouped-input inventory rather than the legacy product path. */
  purpose?: "product" | "input_assembly";
  concurrency?: number;
  maxAttempts?: number;
  pollMs?: number;
}

const API = "/api/v1/uploads/direct";
const URL_BATCH = 20;

function resumeKey(file: File, identity?: string, purpose: DirectUploadOptions["purpose"] = "product"): string {
  const purposeKey = purpose === "input_assembly" ? ":input-assembly" : "";
  if (identity) return `r2s-upload:v2${purposeKey}:${encodeURIComponent(identity)}`;
  if (purpose === "input_assembly") return `r2s-upload:input-assembly:${file.name}:${file.size}:${file.lastModified}`;
  return `r2s-upload:${file.name}:${file.size}:${file.lastModified}`;
}

function readSaved(storage: DirectUploadDeps["storage"], key: string): string | null {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null; // Trình duyệt chặn storage: vẫn upload được, chỉ không nối lại.
  }
}

function writeSaved(storage: DirectUploadDeps["storage"], key: string, value: string | null): void {
  try {
    if (value === null) storage?.removeItem(key);
    else storage?.setItem(key, value);
  } catch {
    // Không lưu được thì bỏ qua; upload vẫn chạy.
  }
}

function aborted(signal: AbortSignal): void {
  if (signal.aborted) throw new ApiError(499, "Đã hủy tải lên");
}

/** Phiên đang UPLOADING của đúng file này (nếu còn), không thì mở phiên mới. */
async function openSession(file: File, options: DirectUploadOptions, deps: DirectUploadDeps): Promise<DirectUploadState> {
  const key = resumeKey(file, options.resumeIdentity, options.purpose);
  const saved = readSaved(deps.storage, key);
  if (saved) {
    try {
      const state = await deps.api<DirectUploadState>(`${API}/${encodeURIComponent(saved)}`);
      if (
        state.size_bytes === file.size &&
        (state.status === "UPLOADING" || (options.keepResumeKey && state.status === "READY"))
      ) return state;
    } catch {
      // Phiên cũ không còn: mở phiên mới bên dưới.
    }
  }
  const state = await deps.api<DirectUploadState>(API, {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      size_bytes: file.size,
      ...(options.purpose === "input_assembly" ? { purpose: options.purpose } : {}),
    }),
  });
  writeSaved(deps.storage, key, state.upload_id);
  return state;
}

export async function directUpload(file: File, options: DirectUploadOptions, deps: DirectUploadDeps): Promise<DirectUploadState> {
  const { signal } = options;
  const concurrency = options.concurrency ?? 4;
  const maxAttempts = options.maxAttempts ?? 4;
  const session = await openSession(file, options, deps);
  const key = resumeKey(file, options.resumeIdentity, options.purpose);
  if (session.status === "READY") {
    options.onProgress(1);
    if (!options.keepResumeKey) writeSaved(deps.storage, key, null);
    return session;
  }
  const { upload_id: uploadId, part_size: partSize, part_count: partCount } = session;
  const partBytes = (n: number) => Math.min(partSize, file.size - (n - 1) * partSize);

  const done = new Set(session.uploaded_parts);
  const pending = Array.from({ length: partCount }, (_, i) => i + 1).filter((n) => !done.has(n));
  let confirmed = [...done].reduce((sum, n) => sum + partBytes(n), 0);
  const inflight = new Map<number, number>();
  const report = () => {
    const loaded = confirmed + [...inflight.values()].reduce((a, b) => a + b, 0);
    options.onProgress(file.size > 0 ? Math.min(1, loaded / file.size) : 1);
  };
  report();

  const urls = new Map<number, string>();
  async function urlFor(n: number, fresh = false): Promise<string> {
    if (!fresh && urls.has(n)) return urls.get(n)!;
    // Xin link theo nhóm các phần kế tiếp để giảm số request mà link không kịp hết hạn.
    const batch = [n, ...pending.filter((m) => m > n && !urls.has(m))].slice(0, URL_BATCH);
    const response = await deps.api<{ urls: Record<string, string> }>(`${API}/${encodeURIComponent(uploadId)}/urls`, {
      method: "POST",
      body: JSON.stringify({ part_numbers: batch }),
    });
    for (const [key, url] of Object.entries(response.urls)) urls.set(Number(key), url);
    return urls.get(n)!;
  }

  async function sendPart(n: number): Promise<void> {
    const body = file.slice((n - 1) * partSize, (n - 1) * partSize + partBytes(n));
    for (let attempt = 1; ; attempt += 1) {
      aborted(signal);
      try {
        const url = await urlFor(n, attempt > 1);
        await deps.putPart(url, body, (loaded) => {
          inflight.set(n, loaded);
          report();
        }, signal);
        inflight.delete(n);
        confirmed += partBytes(n);
        report();
        return;
      } catch (error) {
        inflight.delete(n);
        aborted(signal);
        if (attempt >= maxAttempts) {
          throw error instanceof ApiError ? error : new ApiError(0, "Mất kết nối khi tải video lên; mở lại đúng file để tải tiếp");
        }
        await deps.sleep(500 * 2 ** (attempt - 1));
      }
    }
  }

  const queue = [...pending];
  // Xin trước nhóm link đầu để các luồng song song không cùng gửi request trùng.
  if (queue.length > 0) await urlFor(queue[0]);
  await Promise.all(
    Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
      for (let n = queue.shift(); n !== undefined; n = queue.shift()) await sendPart(n);
    }),
  );

  aborted(signal);
  options.onVerifying?.();
  const completeUrl = `${API}/${encodeURIComponent(uploadId)}/complete`;
  let state = await deps.api<DirectUploadState>(completeUrl, { method: "POST" });
  const pollMs = options.pollMs ?? 1500;
  const nudgeEvery = Math.max(1, Math.round(60_000 / pollMs)); // ~1 phút nhắc server kiểm tra lại
  const maxPolls = Math.round((30 * 60_000) / pollMs); // bỏ cuộc sau ~30 phút
  for (let poll = 1; state.status === "VERIFYING"; poll += 1) {
    if (poll > maxPolls) throw new ApiError(504, "Máy chủ kiểm tra video quá lâu; thử lại sau ít phút");
    aborted(signal);
    await deps.sleep(pollMs);
    // Tác vụ kiểm tra nền có thể mất khi API khởi động lại: thỉnh thoảng gọi lại "hoàn tất".
    state = await deps.api<DirectUploadState>(
      poll % nudgeEvery === 0 ? completeUrl : `${API}/${encodeURIComponent(uploadId)}`,
      poll % nudgeEvery === 0 ? { method: "POST" } : undefined,
    );
  }
  if (!options.keepResumeKey) writeSaved(deps.storage, key, null);
  if (state.status !== "READY") throw new ApiError(422, state.error ?? "Video không qua được bước kiểm tra");
  return state;
}

export function clearDirectUploadResume(
  file: File,
  resumeIdentity: string | undefined,
  storage: DirectUploadDeps["storage"],
  purpose: DirectUploadOptions["purpose"] = "product",
): void {
  writeSaved(storage, resumeKey(file, resumeIdentity, purpose), null);
}

/** PUT bằng XHR để có tiến độ upload (fetch chưa báo tiến độ gửi). */
export const xhrPutPart: PutPart = (url, body, onProgress, signal) =>
  new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", url);
    request.upload.onprogress = (event) => onProgress(event.loaded);
    request.onload = () =>
      request.status >= 200 && request.status < 300
        ? resolve()
        : reject(new ApiError(request.status, `Kho file từ chối phần upload (HTTP ${request.status})`));
    request.onerror = () => reject(new ApiError(0, "Mất kết nối tới kho file"));
    const abort = () => request.abort();
    request.onabort = () => reject(new ApiError(499, "Đã hủy tải lên"));
    signal.addEventListener("abort", abort, { once: true });
    request.send(body);
  });
