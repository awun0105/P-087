/** Bước "Tách vật thể" lỗi (tách theo vật hết số lần thử) phải báo lỗi và cho chọn tiếp ngay tại hàng bước ở tab Tiến trình. */
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import { useObjectify } from "@/features/studio/scene/useObjectify";
import { ApiError } from "@/lib/api/client";
import { STUDIO_STAGES } from "@/features/studio/stages";
import { cancelObjectify, getObjectifyState, requestObjectify, type ObjectifyState } from "@/lib/api/studio";
import type { JobProgress } from "@/lib/contracts/studio";

vi.mock("@/features/studio/scene/AttemptHistory", () => ({ AttemptHistory: () => <div /> }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getObjectifyState: vi.fn(), requestObjectify: vi.fn(), cancelObjectify: vi.fn(),
}));

const done: JobProgress = {
  job_id: "job-1", status: "SUCCEEDED", current_stage: "ST-OBJECT-EXTRACT", attempt: 1,
  started_at: "2026-10-10T00:00:00Z", updated_at: "2026-10-10T01:00:00Z", completed_at: "2026-10-10T01:00:00Z",
  preview_ready: true, error: null, waiting_for: null,
  stages: STUDIO_STAGES.map((meta) => ({ stage_id: meta.id, state: "succeeded", started_at: "2026-10-10T00:00:00Z", completed_at: "2026-10-10T00:10:00Z", error: null })),
};

function objectify(overrides: Partial<ObjectifyState> = {}): ObjectifyState {
  return {
    status: "idle", mode: null, scene_revision: "rev-001", awaiting_choice: false, object_centric: true, available: true, note: null,
    base_revision: null, result_revision: null, error: null, resource_wait: null, cancellation_requested: false, ...overrides,
  };
}
const failed = objectify({ awaiting_choice: true, object_centric: false, note: "tách theo vật lỗi sau 3 lần: hết VRAM" });

function renderTab(props: { canAccept?: boolean } = {}) {
  return render(<ProgressTab jobId="job-1" progress={done} info={null} busy={false} canCancel={false} canAccept={props.canAccept ?? true} onCancel={vi.fn()} />);
}
const row = () => screen.getByText("Tách vật thể").closest("li")!;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("tab Tiến trình: bước Tách vật thể lỗi", () => {
  it("không còn hiện 'đã xong': báo lỗi, lý do và nút chọn tiếp ngay tại hàng bước", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(failed);
    renderTab();
    expect(await within(row()).findByRole("alert")).toHaveTextContent("Tách theo vật không thành công sau 3 lần thử");
    expect(within(row()).getByText("Có thể thử lại")).toBeInTheDocument();
    expect(within(row()).getByRole("button", { name: "Chạy lại tách theo vật" })).toBeInTheDocument();
    expect(within(row()).getByRole("button", { name: "Dùng hộp ứng viên" })).toBeInTheDocument();
    expect(screen.getByText(`${STUDIO_STAGES.length - 1}/${STUDIO_STAGES.length} bước hoàn tất`)).toBeInTheDocument();
    // Không còn đường "xem giai đoạn" cho một bước chưa thành công.
    expect(within(row()).queryByText(/xem chi tiết giai đoạn/)).toBeNull();
  });

  it("bấm nút gửi đúng revision hiện tại và hiện trạng thái đang chạy lại", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(failed);
    vi.mocked(requestObjectify).mockResolvedValue(objectify({ status: "queued", mode: "boxes", awaiting_choice: true, object_centric: false }));
    renderTab();
    fireEvent.click(await within(row()).findByRole("button", { name: "Dùng hộp ứng viên" }));
    await waitFor(() => expect(requestObjectify).toHaveBeenCalledWith("job-1", "rev-001", "boxes"));
    expect(await within(row()).findByRole("button", { name: "Hủy yêu cầu" })).toBeInTheDocument();
    expect(within(row()).queryByRole("alert")).toBeNull();
  });

  it("hủy yêu cầu đang chạy gọi API hủy", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "running", mode: "objectify", object_centric: false, awaiting_choice: true }));
    vi.mocked(cancelObjectify).mockResolvedValue(objectify({ status: "running", cancellation_requested: true, object_centric: false }));
    renderTab();
    fireEvent.click(await within(row()).findByRole("button", { name: "Hủy yêu cầu" }));
    await waitFor(() => expect(cancelObjectify).toHaveBeenCalledWith("job-1"));
    await waitFor(() => expect(within(row()).queryByRole("button", { name: "Hủy yêu cầu" })).toBeNull());
  });

  it("người chỉ xem vẫn thấy lỗi nhưng không có nút thao tác", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(failed);
    renderTab({ canAccept: false });
    expect(await within(row()).findByRole("alert")).toBeInTheDocument();
    expect(within(row()).queryByRole("button", { name: "Dùng hộp ứng viên" })).toBeNull();
    expect(within(row()).queryByRole("button", { name: "Chạy lại tách theo vật" })).toBeNull();
  });

  it("scene tách theo vật bình thường, hoặc lần dựng lại lỗi mà scene vẫn tốt: bước vẫn là đã xong", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "failed", error: "hết VRAM", object_centric: true }));
    renderTab();
    await waitFor(() => expect(getObjectifyState).toHaveBeenCalled());
    expect(screen.getByText(`${STUDIO_STAGES.length}/${STUDIO_STAGES.length} bước hoàn tất`)).toBeInTheDocument();
    expect(within(row()).queryByRole("alert")).toBeNull();
    expect(within(row()).queryByRole("button", { name: "Dùng hộp ứng viên" })).toBeNull();
  });

  it("không hỏi trạng thái tách vật thể khi bước này chưa xong", async () => {
    const running: JobProgress = { ...done, status: "RUNNING", stages: done.stages.map((stage) => stage.stage_id === "ST-OBJECT-EXTRACT" ? { ...stage, state: "running" } : stage) };
    render(<ProgressTab jobId="job-1" progress={running} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(getObjectifyState).not.toHaveBeenCalled();
  });
});

describe("các trường hợp còn lại của hàng bước", () => {
  it("máy không có runtime tách theo vật: chỉ còn nút dùng hộp ứng viên", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue({ ...failed, available: false });
    renderTab();
    expect(await within(row()).findByRole("button", { name: "Dùng hộp ứng viên" })).toBeInTheDocument();
    expect(within(row()).queryByRole("button", { name: "Chạy lại tách theo vật" })).toBeNull();
  });

  it("scene đang dùng hộp ứng viên mà lần dựng lại lỗi: scene vẫn có vật nên bước vẫn là đã xong", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "failed", mode: "objectify", error: "hết VRAM", object_centric: false, awaiting_choice: false }));
    renderTab();
    await waitFor(() => expect(getObjectifyState).toHaveBeenCalled());
    expect(screen.getByText(`${STUDIO_STAGES.length}/${STUDIO_STAGES.length} bước hoàn tất`)).toBeInTheDocument();
    expect(within(row()).queryByRole("alert")).toBeNull();
  });

  it("gặp 409 (scene đã đổi hoặc đã có yêu cầu khác) thì đọc lại trạng thái từ máy chủ", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(failed);
    vi.mocked(requestObjectify).mockRejectedValue(new ApiError(409, "scene đã ở rev-002, không phải rev-001; tải lại rồi thử lại"));
    renderTab();
    fireEvent.click(await within(row()).findByRole("button", { name: "Dùng hộp ứng viên" }));
    expect(await screen.findByText(/tải lại rồi thử lại/)).toBeInTheDocument();
    await waitFor(() => expect(getObjectifyState).toHaveBeenCalledTimes(2));
  });
});

describe("useObjectify: báo revision mới khi yêu cầu do chính nó theo dõi chạy xong", () => {
  it("gọi onRevision đúng một lần với revision kết quả và dừng poll", async () => {
    vi.useFakeTimers();
    try {
      const onRevision = vi.fn();
      vi.mocked(getObjectifyState)
        .mockResolvedValueOnce(failed)
        .mockResolvedValue(objectify({ status: "done", mode: "boxes", scene_revision: "rev-002", result_revision: "rev-002", object_centric: false }));
      vi.mocked(requestObjectify).mockResolvedValue(objectify({ status: "queued", mode: "boxes", object_centric: false, awaiting_choice: true }));
      const { result } = renderHook(() => useObjectify({ jobId: "job-1", onRevision }));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(result.current.state?.awaiting_choice).toBe(true);
      await act(async () => { await result.current.send("boxes"); });
      expect(result.current.pending).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(onRevision).toHaveBeenCalledTimes(1);
      expect(onRevision).toHaveBeenCalledWith("rev-002");
      const calls = vi.mocked(getObjectifyState).mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
      expect(vi.mocked(getObjectifyState).mock.calls.length).toBe(calls);
      expect(onRevision).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
