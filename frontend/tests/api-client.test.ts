/**
 * Test cho ranh giới API.
 *
 * Điều quan trọng nhất: lỗi backend phải thành `ApiError` có `status` và `detail`
 * nguyên văn, không bị nuốt thành giá trị mặc định. UI dựa vào đó để hiện lỗi
 * thật (PRODUCT-05 DoD).
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchApi } from "@/lib/api/client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchApi", () => {
  it("trả ok=true kèm dữ liệu khi backend trả 200", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ projects: [] })));
    const result = await fetchApi<{ projects: unknown[] }>("/api/v1/projects");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.projects).toEqual([]);
    }
  });

  it("giữ nguyên status và detail của envelope lỗi FastAPI", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "không thể tạo job: privacy gate chặn" }, 409)),
    );
    const result = await fetchApi("/api/v1/projects/p/jobs", { method: "POST" });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBeInstanceOf(ApiError);
      expect(result.error.status).toBe(409);
      expect(result.error.detail).toBe("không thể tạo job: privacy gate chặn");
      expect(result.error.isClientError).toBe(true);
    }
  });

  it("gộp detail dạng list của lỗi validate thành chuỗi", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: [{ loc: ["body", "name"], msg: "required" }] }, 422)),
    );
    const result = await fetchApi("/api/v1/projects", { method: "POST" });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.status).toBe(422);
      expect(result.error.detail).toContain("required");
    }
  });

  it("không ném khi backend chết, mà trả lỗi có status 0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }),
    );
    const result = await fetchApi("/api/v1/projects");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.status).toBe(0);
      expect(result.error.detail).toContain("không gọi được backend");
    }
  });

  it("dùng được body lỗi không phải JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("upstream boom", { status: 502 })));
    const result = await fetchApi("/api/v1/projects");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.status).toBe(502);
      expect(result.error.detail).toBe("upstream boom");
    }
  });

  it("đánh dấu lỗi 5xx là lỗi hạ tầng, không phải lỗi client", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "boom" }, 500)));
    const result = await fetchApi("/api/v1/projects");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.isClientError).toBe(false);
    }
  });
});
