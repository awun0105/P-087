/** Bước "Tách vật thể" lỗi (tách theo vật hết số lần thử) phải báo lỗi và cho chọn tiếp ngay tại hàng bước ở tab Tiến trình. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProgressTab } from "@/features/studio/scene/ProgressTab";
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
