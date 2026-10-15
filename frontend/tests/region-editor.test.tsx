/**
 * Region Editor (T-016): API vùng Gaussian, hook xem trước, panel chỉnh vùng, và các điểm bàn giao từ T-015.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { applyObjectRegion, isSceneEditResponse, previewObjectRegion, type RegionPreview } from "@/lib/api/studio";
import type { ObjectRegionCommand } from "@/lib/contracts/api";

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

const command: ObjectRegionCommand = {
  expected_scene_revision: "rev-001",
  membership_checksum: "sha256:" + "a".repeat(64),
  boxes: [{ op: "add", center_m: [0, 0, 0.5], half_extents_m: [0.5, 0.5, 0.5], yaw_rad: 0 }],
  claim_from: [],
};

const preview: RegionPreview = {
  scene_revision: "rev-001",
  membership_checksum: command.membership_checksum,
  object_id: "pallet",
  added_count: 3,
  removed_count: 0,
  object_gaussian_count: 120,
  protected_floor_count: 0,
  overlaps: {},
  claimed: {},
  added_sample_m: [],
  removed_sample_m: [],
  shell_glb_base64: null,
  shell_error: null,
};

describe("API vùng Gaussian", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("preview gửi POST đúng đường dẫn vật và body, không gửi gì khác", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply(preview));

    await expect(previewObjectRegion("job-a", "obj 1", command)).resolves.toMatchObject({ added_count: 3 });

    const [url, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(String(url)).toContain("/jobs/job-a/scene/objects/obj%201/region/preview");
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual(command);
  });

  it("apply trên Draft (201) trả revision mới, trên Ready (202) trả tiến độ dựng lại", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply({ job_id: "job-a", previous_scene_revision: "rev-001", scene_revision: "rev-002", scene: {} }, 201),
    );
    const draft = await applyObjectRegion("job-a", "pallet", command);
    expect(isSceneEditResponse(draft)).toBe(true);
    expect(String(vi.mocked(global.fetch).mock.calls[0][0])).toContain("/jobs/job-a/scene/objects/pallet/region/apply");

    vi.mocked(global.fetch).mockResolvedValueOnce(
      reply({ status: "queued", mode: "region", scene_revision: "rev-001", operation_id: "op-1" }, 202),
    );
    const ready = await applyObjectRegion("job-a", "pallet", command);
    expect(isSceneEditResponse(ready)).toBe(false);
    expect(ready).toMatchObject({ mode: "region", operation_id: "op-1" });
  });

  it("apply bị từ chối (409) ném lỗi có mã và câu của máy chủ", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply({ detail: "revision đã đổi" }, 409));

    await expect(applyObjectRegion("job-a", "pallet", command)).rejects.toMatchObject({
      status: 409,
      detail: "revision đã đổi",
    });
  });
});
