/**
 * Region Editor (T-016): API vùng Gaussian, hook xem trước, panel chỉnh vùng, và các điểm bàn giao từ T-015.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EditableBox } from "@/features/studio/region/box-model";
import { PREVIEW_DEBOUNCE_MS, regionKey, useRegionPreview } from "@/features/studio/region/useRegionPreview";
import { applyObjectRegion, isSceneEditResponse, previewObjectRegion, type RegionPreview } from "@/lib/api/studio";
import type { ObjectRegionCommand } from "@/lib/contracts/api";

// Các test API dùng bản thật; test hook thay bằng bản giả và trả về bản thật sau mỗi test.
vi.mock("@/lib/api/studio", async (original) => {
  const actual = await original<typeof import("@/lib/api/studio")>();
  return { ...actual, previewObjectRegion: vi.fn(actual.previewObjectRegion) };
});
const realPreview = (await vi.importActual<typeof import("@/lib/api/studio")>("@/lib/api/studio")).previewObjectRegion;

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

function box(half: number): EditableBox {
  return { id: "add-1", op: "add", center: [0, 0, 0.5], half: [half, half, 0.5], yaw: 0 };
}

const hookBase = {
  jobId: "job-a",
  objectId: "pallet",
  expectedRevision: "rev-001",
  membershipChecksum: command.membership_checksum,
  claimFrom: [] as string[],
  enabled: true,
};

describe("hook xem trước vùng", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(previewObjectRegion).mockClear();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.mocked(previewObjectRegion).mockImplementation(realPreview);
  });

  it("kéo liên tục chỉ gửi một yêu cầu, sau 250 ms kể từ thay đổi cuối", () => {
    vi.mocked(previewObjectRegion).mockReturnValue(new Promise(() => {}));
    const { rerender } = renderHook(({ boxes }: { boxes: EditableBox[] }) => useRegionPreview({ ...hookBase, boxes }), {
      initialProps: { boxes: [box(0.5)] },
    });

    rerender({ boxes: [box(0.6)] });
    act(() => vi.advanceTimersByTime(100));
    rerender({ boxes: [box(0.7)] });
    act(() => vi.advanceTimersByTime(100));
    rerender({ boxes: [box(0.8)] });

    act(() => vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS - 1));
    expect(previewObjectRegion).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(previewObjectRegion).toHaveBeenCalledTimes(1);
    expect(vi.mocked(previewObjectRegion).mock.calls[0][2].boxes[0].half_extents_m).toEqual([0.8, 0.8, 0.5]);
  });

  it("yêu cầu đang chờ bị huỷ khi box đổi; yêu cầu mới có tín hiệu riêng", () => {
    const signals: AbortSignal[] = [];
    vi.mocked(previewObjectRegion).mockImplementation(async (_job, _object, _command, signal) => {
      signals.push(signal as AbortSignal);
      return new Promise(() => {});
    });
    const { rerender } = renderHook(({ boxes }: { boxes: EditableBox[] }) => useRegionPreview({ ...hookBase, boxes }), {
      initialProps: { boxes: [box(0.5)] },
    });

    act(() => vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS));
    expect(signals).toHaveLength(1);
    expect(signals[0].aborted).toBe(false);

    rerender({ boxes: [box(0.6)] });
    expect(signals[0].aborted).toBe(true);
    act(() => vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS));
    expect(signals).toHaveLength(2);
    expect(signals[1].aborted).toBe(false);
  });

  it("kết quả chỉ hiện khi khoá trùng box hiện tại; box đổi thì đang tải lại", async () => {
    vi.mocked(previewObjectRegion).mockResolvedValue({ ...preview, added_count: 5 });
    const { result: hook, rerender } = renderHook(
      ({ boxes }: { boxes: EditableBox[] }) => useRegionPreview({ ...hookBase, boxes }),
      { initialProps: { boxes: [box(0.5)] } },
    );

    await act(async () => {
      vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS);
      await Promise.resolve();
    });
    expect(hook.current.preview?.added_count).toBe(5);
    expect(hook.current.loading).toBe(false);

    rerender({ boxes: [box(0.6)] });
    expect(hook.current.preview).toBeNull();
    expect(hook.current.loading).toBe(true);
  });

  it("không gọi preview khi bị tắt (box không hợp lệ)", () => {
    const { result } = renderHook(() => useRegionPreview({ ...hookBase, boxes: [box(0.5)], enabled: false }));
    act(() => vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS * 2));
    expect(previewObjectRegion).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
  });

  it("khoá không phụ thuộc thứ tự claim", () => {
    const boxes = [box(0.5)];
    expect(regionKey(boxes, ["b", "a"])).toBe(regionKey(boxes, ["a", "b"]));
    expect(regionKey(boxes, ["a"])).not.toBe(regionKey(boxes, []));
  });
});
