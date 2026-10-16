/**
 * Panel Benchmark (T-033): nhập ground truth, toạ độ canonical khi lưu, 409 giữ nhập liệu, chỉ xem, và hỏi trong panel
 * trước khi bỏ thay đổi. Đổi khung toạ độ được kiểm bằng một điểm biết trước.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BenchmarkPanel, type BenchmarkPickerApi, type BenchmarkPanelProps } from "@/features/studio/value/BenchmarkPanel";
import {
  draftFromTruth,
  isDirty,
  missingObstacleIds,
  nextId,
  parseMinutes,
  truthFromDraft,
} from "@/features/studio/value/benchmark-draft";
import { displayToZUp, sourceToCanonical, toDisplay, type SourceFrame } from "@/features/viewer/source-frame";
import { ApiError } from "@/lib/api/client";
import {
  getBenchmarkTruth,
  putBenchmarkTruth,
  type BenchmarkTruth,
  type BenchmarkTruthResponse,
  type Vec3,
} from "@/lib/api/value";

vi.mock("@/lib/api/value", () => ({
  getBenchmarkTruth: vi.fn(),
  putBenchmarkTruth: vi.fn(),
}));

const EMPTY: BenchmarkTruth = {
  schema_version: "1.0",
  include_in_benchmark: false,
  data_source: "self_capture",
  robot: null,
  distances: [],
  gaps: [],
  key_obstacle_ids: [],
  layouts: {},
  manual_baseline_minutes: null,
  l4: null,
  notes: "",
};

const LOADED: BenchmarkTruthResponse = { version: 3, truth: EMPTY, updated_at: null };

function fakePicker(points: [number, number, number][] = []): BenchmarkPickerApi & { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> } {
  return { points, start: vi.fn(), stop: vi.fn() };
}

const BASE: BenchmarkPanelProps = {
  jobId: "job-1",
  sceneRevision: "rev-2",
  objects: [
    { id: "chair", name: "Ghế" },
    { id: "table", name: "Bàn" },
  ],
  canEdit: true,
  picker: null,
  onClose: () => {},
};

function element(overrides: Partial<BenchmarkPanelProps> = {}) {
  return <BenchmarkPanel {...BASE} {...overrides} />;
}

async function loaded(overrides: Partial<BenchmarkPanelProps> = {}) {
  const view = render(element(overrides));
  await screen.findByRole("button", { name: "Lưu" });
  return view;
}

beforeEach(() => {
  vi.mocked(getBenchmarkTruth).mockReset();
  vi.mocked(putBenchmarkTruth).mockReset();
  vi.mocked(getBenchmarkTruth).mockResolvedValue(LOADED);
});

describe("khung toạ độ (viewer/source-frame)", () => {
  it("điểm biết trước đi qua hiển thị rồi trở về đúng toạ độ canonical", () => {
    const point: Vec3 = [1, 2, 3];
    // Z-up canonical (x, y, z) hiển thị Y-up thành (x, z, −y).
    expect(toDisplay("z_up", point)).toEqual([1, 3, -2]);
    expect(displayToZUp(toDisplay("z_up", point))).toEqual(point);
    expect(sourceToCanonical("z_up", point)).toEqual(point);
  });

  it("khung không phải canonical không được lưu toạ độ", () => {
    const frame: SourceFrame = "colmap";
    expect(() => sourceToCanonical(frame, [1, 2, 3])).toThrow(/không phải hệ canonical/);
  });
});

describe("nháp ground truth", () => {
  it("chuỗi phút và id mới", () => {
    expect(parseMinutes("")).toBeNull();
    expect(parseMinutes("-1")).toBeNull();
    expect(parseMinutes("12.5")).toBe(12.5);
    expect(nextId("d", [{ id: "d1" }, { id: "d3" }])).toBe("d2");
    expect(missingObstacleIds(["chair", "old"], new Set(["chair"]))).toEqual(["old"]);
  });

  it("nháp vừa đọc không bẩn; đổi robot thì bẩn; robot rỗng gửi mặc định", () => {
    const draft = draftFromTruth(EMPTY);
    expect(isDirty(draft, draftFromTruth(EMPTY))).toBe(false);
    expect(isDirty({ ...draft, robot: { ...draft.robot, width_m: 0.8 } }, draft)).toBe(true);
    expect(truthFromDraft(draft).robot).toEqual({ width_m: 0.6, safety_margin_m: 0.05, height_min_m: 0.05, height_max_m: 1.2 });
  });
});

describe("panel Benchmark", () => {
  it("đoạn đo nhận hai điểm đã chọn; lưu gửi đúng toạ độ canonical và phiên bản đã đọc", async () => {
    const first = fakePicker();
    const view = await loaded({ picker: first });
    fireEvent.click(screen.getByRole("button", { name: "Thêm đoạn" }));
    expect(first.start).toHaveBeenCalledTimes(1);

    const second = fakePicker([[1, 2, 3], [4, 6, 3]]);
    view.rerender(element({ picker: second }));
    await screen.findByLabelText("Tên đoạn d1");
    expect(second.stop).toHaveBeenCalled();
    expect(screen.getByText(/Trên scene: 5\.000 m/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Mét thật Đoạn 1"), { target: { value: "5.2" } });
    vi.mocked(putBenchmarkTruth).mockResolvedValue({ ...LOADED, version: 4 });
    fireEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() => expect(putBenchmarkTruth).toHaveBeenCalledTimes(1));
    const [jobId, expectedVersion, truth] = vi.mocked(putBenchmarkTruth).mock.calls[0];
    expect(jobId).toBe("job-1");
    expect(expectedVersion).toBe(3);
    expect(truth.distances).toEqual([{ id: "d1", label: "Đoạn 1", a: [1, 2, 3], b: [4, 6, 3], real_m: 5.2 }]);
  });

  it("409 giữ nguyên nhập liệu và đề nghị tải lại", async () => {
    await loaded();
    fireEvent.change(screen.getByLabelText("Bề rộng (m)"), { target: { value: "0.8" } });
    vi.mocked(putBenchmarkTruth).mockRejectedValue(new ApiError(409, "ground truth đã đổi"));
    fireEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await screen.findByText(/Người khác vừa sửa/);
    expect((screen.getByLabelText("Bề rộng (m)") as HTMLInputElement).value).toBe("0.8");

    vi.mocked(getBenchmarkTruth).mockResolvedValue({ ...LOADED, version: 4 });
    fireEvent.click(screen.getByRole("button", { name: "Tải lại" }));
    await waitFor(() => expect(screen.queryByText(/Người khác vừa sửa/)).toBeNull());
    expect((screen.getByLabelText("Bề rộng (m)") as HTMLInputElement).value).toBe("0.8");
  });

  it("không có quyền ghi thì chỉ xem: ô bị khoá và không có nút Lưu hoạt động", async () => {
    await loaded({ canEdit: false });
    expect((screen.getByLabelText("Bề rộng (m)") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Lưu" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/chỉ có quyền xem/)).toBeTruthy();
  });

  it("đóng khi còn thay đổi chưa lưu thì hỏi trong panel, không gọi onClose ngay", async () => {
    const onClose = vi.fn();
    await loaded({ onClose });
    fireEvent.change(screen.getByLabelText("Bề rộng (m)"), { target: { value: "0.8" } });

    fireEvent.click(screen.getByRole("button", { name: "Đóng panel Benchmark" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog", { name: "Thay đổi chưa lưu" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Ở lại" }));
    expect(screen.queryByRole("alertdialog", { name: "Thay đổi chưa lưu" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Đóng panel Benchmark" }));
    fireEvent.click(screen.getByRole("button", { name: "Bỏ thay đổi" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("gắn bố trí A: gửi revision hiện tại; hiển thị thời điểm do máy chủ trả về", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Gắn revision hiện tại là A" }));
    vi.mocked(putBenchmarkTruth).mockImplementation(async (_job, version, truth) => ({
      version: version + 1,
      updated_at: null,
      truth: { ...truth, layouts: { A: { scene_revision: "rev-2", tagged_at: "2026-10-16T05:00:00Z" } } },
    }));
    fireEvent.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() => expect(putBenchmarkTruth).toHaveBeenCalled());
    expect(vi.mocked(putBenchmarkTruth).mock.calls[0][2].layouts.A?.scene_revision).toBe("rev-2");
    await screen.findByText(/máy chủ đặt lúc/);
  });

  it("A và B cùng revision: không cho lưu và nêu lý do", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Gắn revision hiện tại là A" }));
    fireEvent.click(screen.getByRole("button", { name: "Gắn revision hiện tại là B" }));
    expect(screen.getByText(/phải là hai revision khác nhau/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Lưu" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("vật cản chính đã rời khỏi scene được báo và có thể bỏ chọn", async () => {
    vi.mocked(getBenchmarkTruth).mockResolvedValue({
      ...LOADED,
      truth: { ...EMPTY, key_obstacle_ids: ["chair", "old-box"] },
    });
    await loaded();
    expect(screen.getByRole("alert").textContent).toContain("old-box");

    fireEvent.click(screen.getByRole("button", { name: "Bỏ chọn old-box" }));
    vi.mocked(putBenchmarkTruth).mockResolvedValue({ ...LOADED, version: 4 });
    fireEvent.click(screen.getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(putBenchmarkTruth).toHaveBeenCalled());
    expect(vi.mocked(putBenchmarkTruth).mock.calls[0][2].key_obstacle_ids).toEqual(["chair"]);
  });
});
