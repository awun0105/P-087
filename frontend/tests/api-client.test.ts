/**
 * Test cho ranh giới API.
 *
 * Điều quan trọng nhất: lỗi backend phải thành `ApiError` có `status` và `detail`
 * nguyên văn, không bị nuốt thành giá trị mặc định. UI dựa vào đó để hiện lỗi
 * thật (PRODUCT-05 DoD).
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchApi } from "@/lib/api/client";
import { createSceneFromUpload, getSimulationPackage, retryJob } from "@/lib/api/studio";

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

describe("getSimulationPackage", () => {
  it("fail-closed rejects a download reference paired with a blocked capability", async () => {
    const body = {
      scene_revision: "rev-1",
      source_scene_revision: "rev-0",
      created_at: "2026-10-08T00:00:00Z",
      confirmed_objects: 1,
      environment_triangles: 0,
      carved_triangles: 0,
      preflight: { blocking_result: "PASS", rules: [] },
      export_capability: {
        scene_revision: "rev-1",
        scene_ir_checksum: "sha256:scene",
        status: "blocked",
        requested_mode: "auto",
        effective_mode: "hybrid",
        builder_version: "usd-export-capabilities-v2",
        runtime_qualification: "failed",
        runtime_version: null,
        requirements: {
          collider_types: [],
          static_physics: false,
          dynamic_physics: false,
          local_collider_offsets: false,
          hybrid_visuals: true,
          external_assets: false,
        },
        blockers: [{ code: "USD_RUNTIME_UNQUALIFIED", message: "runtime probe failed", affected_object_ids: [] }],
      },
      package_ref: { artifact_uri: "artifact://candidate", artifact_checksum: "sha256:candidate" },
    };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(body)));

    await expect(getSimulationPackage("job-a")).rejects.toMatchObject({
      status: 502,
      detail: "Backend trả candidate dù capability USD đang bị chặn",
    });
  });
});

describe("run intent idempotency headers", () => {
  it("sends a stable-key header for scene creation and manual retry", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => jsonResponse({
        job_id: "job-1",
        status: "QUEUED",
        job_manifest_checksum: "sha256:job",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("crypto", { randomUUID: vi.fn().mockReturnValueOnce("scene-key").mockReturnValueOnce("retry-key") });

    await createSceneFromUpload("upload-1", "Kho", {
      data_origin: "self_collected_no_pii",
      declared_owner: "QA",
      declared_purpose: "Test",
      rights_to_use_confirmed: true,
      anonymization_confirmed: true,
      retention_acknowledged: true,
    });
    await retryJob("job-1");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("Idempotency-Key")).toBe("scene-key");
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("Idempotency-Key")).toBe("retry-key");
  });
});
