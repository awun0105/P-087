/**
 * Region Editor (T-016): API vùng Gaussian, hook xem trước, phiên và panel chỉnh vùng, và nối overlay vùng vào
 * MetricSceneView.
 */

import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { useState, type RefObject } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { MetricSceneView } from "@/features/studio/MetricSceneView";
import { RegionEditor } from "@/features/studio/region/RegionEditor";
import type { EditableBox } from "@/features/studio/region/box-model";
import {
  addAddBox,
  addSubtractBox,
  canRemoveBox,
  initialRegionSession,
  removeRegionBox,
  selectRegionBox,
  setRegionClaim,
  type RegionSession,
  type RegionViewApi,
} from "@/features/studio/region/region-session";
import { PREVIEW_DEBOUNCE_MS, regionKey, useRegionPreview } from "@/features/studio/region/useRegionPreview";
import type { RegionOverlayHandlers } from "@/features/viewer/region-overlay";
import { ApiError } from "@/lib/api/client";
import { applyObjectRegion, isSceneEditResponse, previewObjectRegion, type RegionPreview } from "@/lib/api/studio";
import type { ObjectRegionCommand, SceneObject } from "@/lib/contracts/api";

// Các test API dùng bản thật; test hook thay bằng bản giả và trả về bản thật sau mỗi test.
vi.mock("@/lib/api/studio", async (original) => {
  const actual = await original<typeof import("@/lib/api/studio")>();
  return {
    ...actual,
    previewObjectRegion: vi.fn(actual.previewObjectRegion),
    applyObjectRegion: vi.fn(actual.applyObjectRegion),
  };
});
const realPreview = (await vi.importActual<typeof import("@/lib/api/studio")>("@/lib/api/studio")).previewObjectRegion;
const realApply = (await vi.importActual<typeof import("@/lib/api/studio")>("@/lib/api/studio")).applyObjectRegion;

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

  it("đổi revision của scene thì kết quả cũ ẩn đi và tính lại", async () => {
    vi.mocked(previewObjectRegion).mockResolvedValue({ ...preview, added_count: 5 });
    const { result: hook, rerender } = renderHook(
      (props: { expectedRevision: string }) => useRegionPreview({ ...hookBase, boxes: [box(0.5)], ...props }),
      { initialProps: { expectedRevision: "rev-001" } },
    );
    await act(async () => {
      vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS);
      await Promise.resolve();
    });
    expect(hook.current.preview?.added_count).toBe(5);

    rerender({ expectedRevision: "rev-002" });
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

// ---- Phiên và panel chỉnh vùng (T-016 bước 3) ----

const pallet = { id: "pallet", name: "Pallet gỗ", primitive_dimensions_xyz_m: [1.2, 0.8, 0.15] } as SceneObject;
const addBox: EditableBox = { id: "add-1", op: "add", center: [0, 0, 0], half: [0.6, 0.4, 0.075], yaw: 0 };
const initial = initialRegionSession(pallet)!;

describe("phiên chỉnh vùng", () => {
  it("vật có kích thước: một box cộng, tâm gốc, nửa kích thước bằng nửa vật", () => {
    expect(initial).toEqual({ objectId: "pallet", boxes: [addBox], selectedId: "add-1", claimFrom: [] });
  });

  it("vật không có kích thước thì chưa có phiên", () => {
    expect(initialRegionSession({ ...pallet, primitive_dimensions_xyz_m: null })).toBeNull();
  });

  it("+ Box cộng: box mới thu còn 80% box đang chọn, cùng tâm và yaw, rồi được chọn", () => {
    const next = addAddBox(initial);
    const created = next.boxes[1];
    expect(created).toMatchObject({ id: "add-2", op: "add", center: [0, 0, 0], yaw: 0 });
    expect(created.half[0]).toBeCloseTo(0.48);
    expect(created.half[1]).toBeCloseTo(0.32);
    expect(created.half[2]).toBeCloseTo(0.06);
    expect(next.selectedId).toBe("add-2");
  });

  it("− Box trừ: box trừ nhỏ 30% đặt ở tâm box đang chọn", () => {
    const shifted: RegionSession = { ...initial, boxes: [{ ...addBox, center: [0.2, 0, 0] }] };
    const next = addSubtractBox(shifted);
    const created = next.boxes[1];
    expect(created).toMatchObject({ id: "sub-2", op: "subtract", center: [0.2, 0, 0] });
    expect(created.half[0]).toBeCloseTo(0.18);
    expect(created.half[1]).toBeCloseTo(0.12);
    expect(created.half[2]).toBeCloseTo(0.0225);
  });

  it("không chọn box thì thêm box dựa trên box cộng đầu", () => {
    const loose: RegionSession = {
      ...initial,
      boxes: [addBox, { id: "add-2", op: "add", center: [1, 0, 0], half: [0.2, 0.2, 0.2], yaw: 0 }],
      selectedId: null,
    };
    expect(addSubtractBox(loose).boxes[2].center).toEqual([0, 0, 0]);
  });

  it("box cộng cuối cùng không xoá được; box trừ xoá được và chọn lại box đầu", () => {
    expect(canRemoveBox(initial, "add-1")).toBe(false);
    const withSub = addSubtractBox(initial);
    expect(canRemoveBox(withSub, "sub-2")).toBe(true);
    const removed = removeRegionBox(withSub, "sub-2");
    expect(removed.boxes.map((item) => item.id)).toEqual(["add-1"]);
    expect(removed.selectedId).toBe("add-1");
    expect(removeRegionBox(initial, "add-1")).toBe(initial);
  });

  it("Lấy luôn bật và tắt id trong claimFrom, không trùng", () => {
    const on = setRegionClaim(initial, "chair", true);
    expect(on.claimFrom).toEqual(["chair"]);
    expect(setRegionClaim(on, "chair", true).claimFrom).toEqual(["chair"]);
    expect(setRegionClaim(on, "chair", false).claimFrom).toEqual([]);
  });

  it("box cộng thứ hai xoá được; chọn id lạ thì bỏ chọn", () => {
    expect(canRemoveBox(addAddBox(initial), "add-1")).toBe(true);
    expect(selectRegionBox(initial, "nope").selectedId).toBeNull();
  });
});

type ApplyResult = Awaited<ReturnType<typeof applyObjectRegion>>;

function Panel({
  start = initial,
  viewApi = { current: null },
  onClose = () => {},
  onApplied = () => {},
  onReload = () => {},
}: {
  start?: RegionSession;
  viewApi?: RefObject<RegionViewApi | null>;
  onClose?: () => void;
  onApplied?: (result: ApplyResult) => void;
  onReload?: () => void;
}) {
  const [session, setSession] = useState(start);
  return (
    <RegionEditor
      jobId="job-a"
      object={pallet}
      sceneRevision="rev-001"
      membershipChecksum={command.membership_checksum}
      nameOf={(id) => (id === "chair" ? "Ghế" : id)}
      session={session}
      onSession={setSession}
      onApplied={onApplied}
      onReload={onReload}
      onClose={onClose}
      viewApi={viewApi}
    />
  );
}

describe("panel chỉnh vùng", () => {
  beforeEach(() => {
    // Mặc định xem trước treo để panel không gọi mạng; các test về bộ đếm đặt kết quả riêng.
    vi.mocked(previewObjectRegion).mockClear();
    vi.mocked(previewObjectRegion).mockImplementation(() => new Promise<RegionPreview>(() => {}));
  });
  afterEach(() => {
    vi.mocked(previewObjectRegion).mockImplementation(realPreview);
  });

  it("mở với một box cộng bằng nửa kích thước vật, đang được chọn", () => {
    render(<Panel />);
    expect(within(screen.getByRole("list", { name: "Box vùng" })).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Cộng #1" })).toHaveAttribute("aria-pressed", "true");
  });

  it("+ Box cộng và − Box trừ thêm box mới rồi chọn nó", () => {
    render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "+ Box cộng" }));
    expect(screen.getByRole("button", { name: "Cộng #2" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "− Box trừ" }));
    expect(screen.getByRole("button", { name: "Trừ #3" })).toHaveAttribute("aria-pressed", "true");
  });

  it("không xoá box cộng cuối cùng; xoá được box trừ và box cộng khi còn box cộng khác", () => {
    render(<Panel />);
    expect(screen.getByRole("button", { name: "Xoá Cộng #1" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "− Box trừ" }));
    fireEvent.click(screen.getByRole("button", { name: "Xoá Trừ #2" }));
    expect(screen.queryByRole("button", { name: "Trừ #2" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ Box cộng" }));
    fireEvent.click(screen.getByRole("button", { name: "Xoá Cộng #1" }));
    expect(screen.getByRole("button", { name: "Xoá Cộng #1" })).toBeDisabled();
  });

  it("Delete xoá box đang chọn, không xoá box cộng cuối cùng", () => {
    render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "− Box trừ" }));
    fireEvent.keyDown(window, { key: "Delete" });
    expect(screen.queryByRole("button", { name: "Trừ #2" })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Delete" });
    expect(screen.getByRole("button", { name: "Cộng #1" })).toBeInTheDocument();
  });

  it("Delete đang gõ trong ô nhập thì không xoá box", () => {
    render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "− Box trừ" }));
    const field = document.createElement("input");
    document.body.appendChild(field);
    fireEvent.keyDown(field, { key: "Delete" });
    expect(screen.getByRole("button", { name: "Trừ #2" })).toBeInTheDocument();
    field.remove();
  });

  it("Đặt lại đưa về một box cộng ban đầu", () => {
    render(<Panel />);
    fireEvent.click(screen.getByRole("button", { name: "+ Box cộng" }));
    fireEvent.click(screen.getByRole("button", { name: "− Box trừ" }));
    fireEvent.click(screen.getByRole("button", { name: "Đặt lại" }));
    expect(within(screen.getByRole("list", { name: "Box vùng" })).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Cộng #1" })).toHaveAttribute("aria-pressed", "true");
  });

  it("góc nhìn gọi overlay; khi overlay chưa nối thì khoá các nút và báo lý do", () => {
    const viewFrom = vi.fn(() => false);
    const viewApi: RefObject<RegionViewApi | null> = { current: { viewFrom, isGesturing: () => false } };
    render(<Panel viewApi={viewApi} />);
    fireEvent.click(screen.getByRole("button", { name: "Trước" }));
    expect(viewFrom).toHaveBeenCalledWith("front");
    expect(screen.getByRole("button", { name: "Trước" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cạnh" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Trên" })).toHaveAttribute("title", expect.stringContaining("chưa sẵn sàng"));
  });

  it("góc nhìn cần box đang chọn", () => {
    render(<Panel start={{ ...initial, selectedId: null }} />);
    expect(screen.getByRole("button", { name: "Trên" })).toBeDisabled();
  });

  it("Esc đóng panel khi không kéo; khi đang kéo thì Esc thuộc về overlay", () => {
    const onClose = vi.fn();
    const isGesturing = vi.fn(() => true);
    const viewApi: RefObject<RegionViewApi | null> = { current: { viewFrom: () => true, isGesturing } };
    render(<Panel viewApi={viewApi} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    isGesturing.mockReturnValue(false);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("nút đóng gọi onClose", () => {
    const onClose = vi.fn();
    render(<Panel onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Đóng chỉnh vùng" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("báo lỗi khi box không hợp lệ", () => {
    const thin: EditableBox = { ...addBox, half: [0.001, 0.4, 0.075] };
    render(<Panel start={{ ...initial, boxes: [thin] }} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("không gọi xem trước khi box không hợp lệ", () => {
    const thin: EditableBox = { ...addBox, half: [0.001, 0.4, 0.075] };
    vi.useFakeTimers();
    try {
      render(<Panel start={{ ...initial, boxes: [thin] }} />);
      act(() => vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS * 2));
      expect(previewObjectRegion).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("đang tính thì hiện spinner; xong thì hiện bộ đếm và bảo vệ sàn", async () => {
    vi.mocked(previewObjectRegion).mockResolvedValue({ ...preview, protected_floor_count: 4 });
    render(<Panel />);
    expect(screen.getByText("Đang tính vùng…")).toBeInTheDocument();
    expect(await screen.findByText("+3 / −0 · tổng 120")).toBeInTheDocument();
    expect(screen.getByText("Bảo vệ sàn: 4")).toBeInTheDocument();
    expect(screen.queryByText("Đang tính vùng…")).not.toBeInTheDocument();
  });

  it("đổi box thì bộ đếm cũ ẩn đi và đang tính lại", async () => {
    vi.mocked(previewObjectRegion).mockResolvedValue(preview);
    render(<Panel />);
    expect(await screen.findByText("+3 / −0 · tổng 120")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ Box cộng" }));
    expect(screen.queryByText("+3 / −0 · tổng 120")).not.toBeInTheDocument();
    expect(screen.getByText("Đang tính vùng…")).toBeInTheDocument();
  });

  it("vật chồng lấn nêu tên và số Gaussian; Lấy luôn đưa id vào claim_from của lần xem trước sau", async () => {
    vi.mocked(previewObjectRegion).mockResolvedValue({ ...preview, overlaps: { chair: 42 } });
    render(<Panel />);
    expect(await screen.findByText("Box chồng lên Ghế (42 Gaussian) — giữ chủ cũ")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Lấy luôn từ Ghế" }));
    expect(await screen.findByText("Box chồng lên Ghế (42 Gaussian) — sẽ lấy về vật này")).toBeInTheDocument();
    expect(vi.mocked(previewObjectRegion).mock.lastCall![2].claim_from).toEqual(["chair"]);
  });

  it("vỏ chưa dựng được thì nêu lý do trong cảnh báo", async () => {
    vi.mocked(previewObjectRegion).mockResolvedValue({ ...preview, shell_error: "lưới vỏ rỗng" });
    render(<Panel />);
    expect(
      await screen.findByText("Vỏ chưa dựng được: lưới vỏ rỗng. Apply vẫn được nhưng Tạo mesh sẽ báo lỗi cho vật này."),
    ).toBeInTheDocument();
  });

  it("xem trước lỗi thì hiện câu của máy chủ", async () => {
    vi.mocked(previewObjectRegion).mockRejectedValue(new ApiError(422, "Box lệch khỏi sàn"));
    render(<Panel />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Box lệch khỏi sàn");
  });
});

describe("Apply và Huỷ", () => {
  const applied = { job_id: "job-a", previous_scene_revision: "rev-001", scene_revision: "rev-002", scene: {} } as unknown as ApplyResult;

  beforeEach(() => {
    vi.mocked(previewObjectRegion).mockClear();
    vi.mocked(previewObjectRegion).mockResolvedValue(preview);
    vi.mocked(applyObjectRegion).mockClear();
  });
  afterEach(() => {
    vi.mocked(previewObjectRegion).mockImplementation(realPreview);
    vi.mocked(applyObjectRegion).mockImplementation(realApply);
  });

  it("Apply tắt cho tới khi có xem trước khớp box; đổi box thì tắt lại", async () => {
    render(<Panel />);
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
    expect(await screen.findByText("+3 / −0 · tổng 120")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "+ Box cộng" }));
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
    expect(await screen.findByText("+3 / −0 · tổng 120")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
  });

  it("Apply gửi revision, membership, box và claim hiện tại; kết quả 201 đưa cho cha", async () => {
    vi.mocked(previewObjectRegion).mockResolvedValue({ ...preview, overlaps: { chair: 42 } });
    vi.mocked(applyObjectRegion).mockResolvedValue(applied);
    const onApplied = vi.fn();
    render(<Panel onApplied={onApplied} />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Lấy luôn từ Ghế" }));
    expect(await screen.findByText("Box chồng lên Ghế (42 Gaussian) — sẽ lấy về vật này")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(applied));
    expect(applyObjectRegion).toHaveBeenCalledWith("job-a", "pallet", {
      expected_scene_revision: "rev-001",
      membership_checksum: command.membership_checksum,
      boxes: [{ op: "add", center_m: [0, 0, 0], half_extents_m: [0.6, 0.4, 0.075], yaw_rad: 0 }],
      claim_from: ["chair"],
    });
  });

  it("Apply trên scene Ready (202) đưa kết quả tiến độ cho cha", async () => {
    const queued = { status: "queued", mode: "region", scene_revision: "rev-001", operation_id: "op-1" } as unknown as ApplyResult;
    vi.mocked(applyObjectRegion).mockResolvedValue(queued);
    const onApplied = vi.fn();
    render(<Panel onApplied={onApplied} />);
    await screen.findByText("+3 / −0 · tổng 120");
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(queued));
  });

  it("409: báo scene đã đổi, giữ nguyên box, nút Tải lại gọi onReload", async () => {
    vi.mocked(applyObjectRegion).mockRejectedValue(new ApiError(409, "revision đã đổi"));
    const onReload = vi.fn();
    render(<Panel onReload={onReload} />);
    await screen.findByText("+3 / −0 · tổng 120");
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText("Scene đã đổi ở lượt khác. Tải lại để chỉnh tiếp.")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Box vùng" })).getAllByRole("listitem")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Tải lại" }));
    expect(onReload).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Scene đã đổi ở lượt khác. Tải lại để chỉnh tiếp.")).not.toBeInTheDocument();
  });

  it("422: hiện câu của máy chủ", async () => {
    vi.mocked(applyObjectRegion).mockRejectedValue(
      new ApiError(422, "Scene đã có hình học; tính năng dựng lại vật sẽ có ở bước sau."),
    );
    render(<Panel />);
    await screen.findByText("+3 / −0 · tổng 120");
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Scene đã có hình học");
  });

  it("Huỷ đóng panel và không gửi ghi nào", () => {
    const onClose = vi.fn();
    render(<Panel onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Huỷ" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(applyObjectRegion).not.toHaveBeenCalled();
  });
});

// ---- MetricSceneView nối overlay vùng (bàn giao T-015) ----

// Viewer giả: PlayCanvasScene chỉ đưa props ra ngoài; SceneOverlay và overlay vùng được ghi lại để đọc lời gọi.
type FakeRegion = {
  objectId: string;
  handlers: RegionOverlayHandlers;
  setBoxes: Mock;
  viewFrom: Mock;
  isGesturing: Mock;
  destroy: Mock;
};
const viewer = vi.hoisted(() => ({
  viewerProps: vi.fn(),
  entities: new Map<string, object>(),
  sceneOverlays: [] as Array<{ bindViewerGotoPose: Mock }>,
  regionOverlays: [] as FakeRegion[],
}));
vi.mock("@/features/viewer/scene-overlay", () => ({
  SceneOverlay: class {
    attachGizmo = vi.fn();
    bindViewerGotoPose = vi.fn();
    destroy = vi.fn();
    detachGizmo = vi.fn();
    setObjects = vi.fn();
    setBoxes = vi.fn();
    setColliders = vi.fn();
    setSurfaceMarkers = vi.fn();
    setSplatVisible = vi.fn();
    setCollision = vi.fn();
    collisionPositions = () => null;
    loadCollision = vi.fn(async () => 0);
    pickCollisionTriangle = vi.fn();
    constructor() {
      viewer.sceneOverlays.push(this);
    }
    isAlive = () => true;
    objectEntity = (id: string) => viewer.entities.get(id) ?? null;
  },
}));
vi.mock("@/features/viewer/region-overlay", () => ({
  RegionOverlay: class {
    objectId: string;
    handlers: RegionOverlayHandlers;
    setBoxes = vi.fn();
    viewFrom = vi.fn(() => true);
    isGesturing = vi.fn(() => false);
    destroy = vi.fn();
    constructor(_host: unknown, objectId: string, handlers: RegionOverlayHandlers) {
      this.objectId = objectId;
      this.handlers = handlers;
      viewer.regionOverlays.push(this);
    }
  },
}));
vi.mock("@/features/viewer/third-person", () => ({
  WALK_EYE_HEIGHT_M: 1.3,
  ThirdPersonRig: class {
    destroy = vi.fn();
    setActive = vi.fn();
    setCollision = vi.fn();
  },
}));
vi.mock("@/features/viewer/PlayCanvasScene", async (original) => ({
  ...(await original<typeof import("@/features/viewer/PlayCanvasScene")>()),
  usePlayCanvasCapability: () => ["ready", vi.fn()],
  PlayCanvasScene: (props: object) => {
    viewer.viewerProps(props);
    return <div data-testid="viewer-surface" />;
  },
}));

const visualRef = { artifact_uri: "artifact://jobs/j/background.sog", artifact_checksum: "sha256:visual" };
const palletObject = {
  id: "pallet",
  url: null,
  position: [0, 0, 0] as [number, number, number],
  rotation_xyzw: [0, 0, 0, 1] as [number, number, number, number],
  visible: true,
};
type RegionEditProp = NonNullable<Parameters<typeof MetricSceneView>[0]["regionEdit"]>;
type ViewerProps = {
  regionEdit: RegionEditProp | null;
  objects?: (typeof palletObject)[];
  regionApi?: RefObject<RegionViewApi | null>;
};

function viewerElement({ regionEdit, objects = [palletObject], regionApi }: ViewerProps) {
  return (
    <MetricSceneView
      jobId="j"
      visual={visualRef}
      cameras={[]}
      objects={objects}
      regionEdit={regionEdit}
      regionApi={regionApi}
    />
  );
}

/** Dựng viewer và trao `onApp` (viewer đã sẵn sàng) để overlay được tạo, như khi PlayCanvas mở xong. */
function mountViewer(props: ViewerProps) {
  const view = render(viewerElement(props));
  const controls = {
    gotoPose: vi.fn(() => true),
    setObjectCollision: vi.fn(),
    setCameraMode: vi.fn(),
    setInputEnabled: vi.fn(),
  };
  act(() => viewer.viewerProps.mock.lastCall![0].onApp({}, controls));
  return { ...view, controls, update: (next: ViewerProps) => view.rerender(viewerElement(next)) };
}

function regionEdit(boxes: EditableBox[], objectId = "pallet") {
  return { objectId, boxes, selectedId: boxes[0]?.id ?? null, onChange: vi.fn(), onSelect: vi.fn() };
}

describe("MetricSceneView nối overlay vùng", () => {
  beforeEach(() => {
    viewer.entities.clear();
    viewer.entities.set("pallet", {});
    viewer.sceneOverlays.length = 0;
    viewer.regionOverlays.length = 0;
  });

  it("đưa lệnh chuyển camera của viewer vào overlay để góc nhìn dùng được", () => {
    const { controls } = mountViewer({ regionEdit: regionEdit([addBox]) });
    const goto = viewer.sceneOverlays[0].bindViewerGotoPose.mock.lastCall![0] as (pose: unknown) => boolean;
    const pose = { position: [1, 2, 3], target: [0, 0, 0], fov: 50 };
    expect(goto(pose)).toBe(true);
    expect(controls.gotoPose).toHaveBeenCalledWith(pose);
  });

  it("vẽ overlay vùng cho vật đang chỉnh với box và box chọn hiện tại", () => {
    mountViewer({ regionEdit: regionEdit([addBox]) });
    expect(viewer.regionOverlays).toHaveLength(1);
    expect(viewer.regionOverlays[0].objectId).toBe("pallet");
    expect(viewer.regionOverlays[0].setBoxes).toHaveBeenLastCalledWith([addBox], "add-1");
  });

  it("box và chọn từ overlay (onChange, onSelect) được trả về cho cha", () => {
    const region = regionEdit([addBox]);
    mountViewer({ regionEdit: region });
    const moved: EditableBox[] = [{ ...addBox, center: [0.1, 0, 0] }];
    viewer.regionOverlays[0].handlers.onChange(moved);
    viewer.regionOverlays[0].handlers.onSelect(null);
    expect(region.onChange).toHaveBeenCalledWith(moved);
    expect(region.onSelect).toHaveBeenCalledWith(null);
  });

  it("không ghi box vào overlay khi đang kéo; box thả đến từ cha thì ghi", () => {
    const region = regionEdit([addBox]);
    const { update } = mountViewer({ regionEdit: region });
    const overlay = viewer.regionOverlays[0];
    overlay.setBoxes.mockClear();
    overlay.isGesturing.mockReturnValue(true);
    const previewed: EditableBox[] = [{ ...addBox, half: [0.7, 0.4, 0.075] }];
    update({ regionEdit: { ...region, boxes: previewed } });
    expect(overlay.setBoxes).not.toHaveBeenCalled();
    overlay.isGesturing.mockReturnValue(false);
    const released: EditableBox[] = [{ ...addBox, half: [0.8, 0.4, 0.075] }];
    update({ regionEdit: { ...region, boxes: released } });
    expect(overlay.setBoxes).toHaveBeenLastCalledWith(released, "add-1");
  });

  it("dựng lại entity của vật thì gỡ overlay cũ và tạo overlay mới với box hiện tại", () => {
    const region = regionEdit([addBox]);
    const { update } = mountViewer({ regionEdit: region });
    const first = viewer.regionOverlays[0];
    viewer.entities.set("pallet", {});
    update({ regionEdit: region, objects: [{ ...palletObject }] });
    expect(first.destroy).toHaveBeenCalledTimes(1);
    expect(viewer.regionOverlays).toHaveLength(2);
    expect(viewer.regionOverlays[1].setBoxes).toHaveBeenLastCalledWith([addBox], "add-1");
  });

  it("đóng panel gỡ overlay; mở lại tạo overlay mới; unmount cũng gỡ", () => {
    const region = regionEdit([addBox]);
    const { update, unmount } = mountViewer({ regionEdit: region });
    const first = viewer.regionOverlays[0];
    update({ regionEdit: null });
    expect(first.destroy).toHaveBeenCalledTimes(1);
    update({ regionEdit: region });
    const second = viewer.regionOverlays[1];
    unmount();
    expect(second.destroy).toHaveBeenCalledTimes(1);
  });

  it("không có vật đang chỉnh thì không tạo overlay vùng", () => {
    mountViewer({ regionEdit: null });
    expect(viewer.regionOverlays).toHaveLength(0);
  });

  it("vật đang chỉnh chưa có trên viewport thì báo và chưa tạo overlay", () => {
    mountViewer({ regionEdit: regionEdit([addBox], "other") });
    expect(viewer.regionOverlays).toHaveLength(0);
    expect(screen.getByText(/chưa có trên viewport/)).toBeInTheDocument();
  });

  it("regionApi: góc nhìn và trạng thái kéo đi qua overlay vùng", () => {
    const api: RefObject<RegionViewApi | null> = { current: null };
    mountViewer({ regionEdit: regionEdit([addBox]), regionApi: api });
    const overlay = viewer.regionOverlays[0];
    overlay.viewFrom.mockReturnValueOnce(false);
    expect(api.current?.viewFrom("side")).toBe(false);
    expect(overlay.viewFrom).toHaveBeenCalledWith("side");
    overlay.isGesturing.mockReturnValue(true);
    expect(api.current?.isGesturing()).toBe(true);
  });
});
