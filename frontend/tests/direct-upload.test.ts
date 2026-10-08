import { describe, expect, it, vi } from "vitest";

import { directUpload, type DirectUploadDeps, type DirectUploadState, type PutPart } from "@/lib/api/directUpload";

const PART = 4;

/** Server + kho file giả: đủ các route `/uploads/direct` mà client dùng. */
function fakeServer(options: { size: number; uploaded?: number[]; verify?: "READY" | "FAILED" } = { size: 10 }) {
  const count = Math.ceil(options.size / PART);
  const stored = new Map<number, number>((options.uploaded ?? []).map((n) => [n, PART]));
  let state: DirectUploadState = {
    upload_id: "upload-1",
    original_name: "kho.mp4",
    size_bytes: options.size,
    part_size: PART,
    part_count: count,
    status: "UPLOADING",
    error: null,
    uploaded_parts: [...stored.keys()],
  };
  const calls: string[] = [];
  let polls = 0;
  const api = vi.fn(async (path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push(`${method} ${path}`);
    if (method === "POST" && path === "/api/v1/uploads/direct") return state;
    if (path.endsWith("/urls")) {
      const { part_numbers } = JSON.parse(String(init?.body)) as { part_numbers: number[] };
      return { urls: Object.fromEntries(part_numbers.map((n) => [n, `https://store/part-${n}?v=${calls.length}`])) };
    }
    if (path.endsWith("/complete")) {
      state = { ...state, status: "VERIFYING" };
      return state;
    }
    if (state.status === "VERIFYING" && ++polls >= 2) {
      state = {
        ...state,
        status: options.verify ?? "READY",
        error: options.verify === "FAILED" ? "Kích thước khác khai báo" : null,
      };
    }
    return { ...state, uploaded_parts: [...stored.keys()].sort() };
  });
  const putPart = vi.fn<PutPart>(async (url, body, onProgress) => {
    onProgress(body.size);
    stored.set(Number(/part-(\d+)/.exec(url)![1]), body.size);
  });
  const memory = new Map<string, string>();
  const storage = {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => void memory.set(key, value),
    removeItem: (key: string) => void memory.delete(key),
  };
  const deps: DirectUploadDeps = { api: api as DirectUploadDeps["api"], putPart, sleep: async () => {}, storage };
  return { deps, api, putPart, calls, memory, stored };
}

function file(size: number): File {
  return new File([new Uint8Array(size)], "kho.mp4", { type: "video/mp4", lastModified: 1 });
}

describe("directUpload", () => {
  it("upload đủ phần, báo tiến độ tới 100%, chờ server kiểm tra rồi xóa id nối lại", async () => {
    const server = fakeServer({ size: 10 });
    const progress: number[] = [];
    const verifying = vi.fn();
    const result = await directUpload(
      file(10),
      { onProgress: (f) => progress.push(f), onVerifying: verifying, signal: new AbortController().signal },
      server.deps,
    );
    expect(result.status).toBe("READY");
    expect(server.putPart).toHaveBeenCalledTimes(3);
    expect(progress.at(-1)).toBe(1);
    expect(verifying).toHaveBeenCalledOnce();
    expect(server.memory.size).toBe(0);
    // Phần cuối nhỏ hơn part_size.
    expect(server.putPart.mock.calls.map((call) => (call[1] as Blob).size).sort()).toEqual([2, 4, 4]);
  });

  it("nối lại phiên cũ và chỉ gửi các phần còn thiếu", async () => {
    const server = fakeServer({ size: 10, uploaded: [1] });
    server.memory.set("r2s-upload:kho.mp4:10:1", "upload-1");
    const progress: number[] = [];
    await directUpload(file(10), { onProgress: (f) => progress.push(f), signal: new AbortController().signal }, server.deps);
    expect(server.calls).not.toContain("POST /api/v1/uploads/direct");
    expect(server.putPart.mock.calls.map((call) => call[0] as string).some((url) => url.includes("part-1"))).toBe(false);
    expect(progress[0]).toBeCloseTo(0.4); // phần 1 đã có sẵn trước khi gửi tiếp
  });

  it("video đã chuẩn hóa giữ phiên READY để retry bước gắn receipt bằng đúng identity nội dung", async () => {
    const server = fakeServer({ size: 10 });
    const resumeIdentity = "user-7:sha256:prepared:sha256:manifest";
    const key = `r2s-upload:v2:${encodeURIComponent(resumeIdentity)}`;
    const options = {
      onProgress: () => {},
      signal: new AbortController().signal,
      resumeIdentity,
      keepResumeKey: true,
    };

    await directUpload(file(10), options, server.deps);
    expect(server.memory.get(key)).toBe("upload-1");
    const uploadedParts = server.putPart.mock.calls.length;

    const resumed = await directUpload(file(10), options, server.deps);
    expect(resumed.status).toBe("READY");
    expect(server.putPart).toHaveBeenCalledTimes(uploadedParts);
    expect(server.memory.get(key)).toBe("upload-1");
    expect(server.memory.has("r2s-upload:kho.mp4:10:1")).toBe(false);
  });

  it("tách phiên và khóa resume cho input assembly khỏi upload product cùng file", async () => {
    const server = fakeServer({ size: 10 });
    const resumeIdentity = "user-7:sha256:sidecar";
    const productKey = `r2s-upload:v2:${encodeURIComponent(resumeIdentity)}`;
    const assemblyKey = `r2s-upload:v2:input-assembly:${encodeURIComponent(resumeIdentity)}`;
    server.memory.set(productKey, "product-session");

    await directUpload(
      file(10),
      {
        onProgress: () => {},
        signal: new AbortController().signal,
        resumeIdentity,
        purpose: "input_assembly",
        keepResumeKey: true,
      },
      server.deps,
    );

    const openSession = server.api.mock.calls.find(([path, init]) => path === "/api/v1/uploads/direct" && init?.method === "POST");
    expect(JSON.parse(String(openSession?.[1]?.body))).toEqual({
      filename: "kho.mp4",
      size_bytes: 10,
      purpose: "input_assembly",
    });
    expect(server.memory.get(productKey)).toBe("product-session");
    expect(server.memory.get(assemblyKey)).toBe("upload-1");
  });

  it("thử lại phần lỗi với link mới", async () => {
    const server = fakeServer({ size: 10 });
    const original = server.putPart.getMockImplementation()!;
    let failed = false;
    server.putPart.mockImplementation(async (url, body, onProgress, signal) => {
      if (url.includes("part-2") && !failed) {
        failed = true;
        throw new Error("network");
      }
      return original(url, body, onProgress, signal);
    });
    await directUpload(file(10), { onProgress: () => {}, signal: new AbortController().signal, concurrency: 1 }, server.deps);
    const part2 = server.putPart.mock.calls.filter((call) => (call[0] as string).includes("part-2"));
    expect(part2).toHaveLength(2);
    expect(part2[0][0]).not.toBe(part2[1][0]);
  });

  it("bỏ cuộc sau số lần thử tối đa và giữ id để nối lại", async () => {
    const server = fakeServer({ size: 10 });
    server.putPart.mockRejectedValue(new Error("offline"));
    await expect(
      directUpload(file(10), { onProgress: () => {}, signal: new AbortController().signal, maxAttempts: 2 }, server.deps),
    ).rejects.toThrow(/tải tiếp/);
    expect(server.memory.get("r2s-upload:kho.mp4:10:1")).toBe("upload-1");
  });

  it("hủy thì dừng ngay", async () => {
    const server = fakeServer({ size: 10 });
    const controller = new AbortController();
    controller.abort();
    await expect(directUpload(file(10), { onProgress: () => {}, signal: controller.signal }, server.deps)).rejects.toThrow(
      "Đã hủy tải lên",
    );
    expect(server.putPart).not.toHaveBeenCalled();
  });

  it("server từ chối khi kiểm tra thì báo lỗi rõ", async () => {
    const server = fakeServer({ size: 10, verify: "FAILED" });
    await expect(
      directUpload(file(10), { onProgress: () => {}, signal: new AbortController().signal }, server.deps),
    ).rejects.toThrow("Kích thước khác khai báo");
  });
});

describe("directUpload — kiểm tra kẹt", () => {
  it("nhắc server kiểm tra lại định kỳ và bỏ cuộc sau giới hạn", async () => {
    const server = fakeServer({ size: 4 });
    // Server không bao giờ rời VERIFYING (vd tác vụ nền mất khi API khởi động lại).
    server.api.mockImplementation(async (path: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST" && path === "/api/v1/uploads/direct") {
        return { upload_id: "upload-1", original_name: "kho.mp4", size_bytes: 4, part_size: 4, part_count: 1, status: "UPLOADING", error: null, uploaded_parts: [] };
      }
      if (path.endsWith("/urls")) return { urls: { 1: "https://store/part-1" } };
      return { upload_id: "upload-1", original_name: "kho.mp4", size_bytes: 4, part_size: 4, part_count: 1, status: "VERIFYING", error: null, uploaded_parts: [] };
    });
    await expect(
      directUpload(file(4), { onProgress: () => {}, signal: new AbortController().signal, pollMs: 60_000 }, server.deps),
    ).rejects.toThrow("quá lâu");
    const completes = server.api.mock.calls.filter(([path, init]) => String(path).endsWith("/complete") && init?.method === "POST");
    expect(completes.length).toBeGreaterThan(1); // có gọi lại "hoàn tất"
  });
});
