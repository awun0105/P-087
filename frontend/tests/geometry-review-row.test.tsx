/** Hàng "Duyệt vật & Tạo mesh" trong tab Tiến trình (T-021): trạng thái, phụ đề và nút theo bảng. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import { STUDIO_STAGES } from "@/features/studio/stages";
import { buildObjectGeometry, cancelObjectify, getObjectifyState, type ObjectifyState } from "@/lib/api/studio";
import type { JobProgress } from "@/lib/contracts/studio";

vi.mock("@/features/studio/scene/AttemptHistory", () => ({ AttemptHistory: () => <div /> }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getObjectifyState: vi.fn(),
  requestObjectify: vi.fn(),
  cancelObjectify: vi.fn(),
  buildObjectGeometry: vi.fn(),
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
    base_revision: null, result_revision: null, error: null, resource_wait: null, cancellation_requested: false,
    object_geometry: "awaiting_review", ...overrides,
  };
}

function renderTab(state: ObjectifyState, props: { canAccept?: boolean; onOpenStudio?: () => void } = {}) {
  vi.mocked(getObjectifyState).mockResolvedValue(state);
  return render(
    <ProgressTab
      jobId="job-1"
      progress={done}
      info={null}
      busy={false}
      canCancel={false}
      canAccept={props.canAccept ?? true}
      onCancel={vi.fn()}
      onOpenStudio={props.onOpenStudio}
    />,
  );
}

/** Hàng theo tiêu đề; hàng ảo chỉ xuất hiện sau khi trạng thái tách vật được đọc, nên chờ bằng findBy. */
const rowOf = async (title: string) => (await screen.findByText(title)).closest("li")!;
const GEOMETRY_ROW = "Duyệt vật & Tạo mesh";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("hàng Duyệt vật & Tạo mesh trên tab Tiến trình", () => {
  it("Draft chờ duyệt: hàng nằm ngay sau Tách vật thể, chờ bạn, có nút mở Studio", async () => {
    const onOpenStudio = vi.fn();
    renderTab(objectify({ status: "idle" }), { onOpenStudio });
    const geometry = await rowOf(GEOMETRY_ROW);

    expect(await within(geometry).findByText("Chỉnh vùng nếu cần, rồi Tạo mesh")).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    expect(rows.indexOf(geometry)).toBe(rows.indexOf(await rowOf("Tách vật thể")) + 1);
    expect(within(geometry).getByText("Đang chờ bạn")).toBeInTheDocument();
    expect(within(geometry).queryByRole("link")).toBeNull();
    fireEvent.click(within(geometry).getByRole("button", { name: "Mở để duyệt" }));
    expect(onOpenStudio).toHaveBeenCalledTimes(1);
  });

  it("đang dựng vỏ: hiện phase tiếng Việt và nút Hủy; Tách vật thể vẫn xong", async () => {
    renderTab(objectify({ status: "running", mode: "geometry", phase: "shell", operation_id: "op-1" }));

    const geometry = await rowOf(GEOMETRY_ROW);
    expect(await within(geometry).findByText("Dựng vỏ vật")).toBeInTheDocument();
    expect(within(await rowOf("Tách vật thể")).queryByRole("button", { name: "Hủy yêu cầu" })).toBeNull();
    fireEvent.click(within(geometry).getByRole("button", { name: "Hủy yêu cầu" }));
    await waitFor(() => expect(cancelObjectify).toHaveBeenCalledWith("job-1", "op-1"));
  });

  it("Tạo mesh lỗi: hiện lý do và hai nút; Thử lại gửi đúng revision hiện tại", async () => {
    const onOpenStudio = vi.fn();
    vi.mocked(buildObjectGeometry).mockResolvedValue(objectify({ status: "queued", mode: "geometry", base_revision: "rev-001" }));
    renderTab(objectify({ status: "failed", mode: "geometry", base_revision: "rev-001", error: "Vỏ của Ghế không dựng được" }), { onOpenStudio });

    const geometry = await rowOf(GEOMETRY_ROW);
    expect(await within(geometry).findByText("Vỏ của Ghế không dựng được")).toBeInTheDocument();
    fireEvent.click(within(geometry).getByRole("button", { name: "Mở để sửa vùng" }));
    expect(onOpenStudio).toHaveBeenCalledTimes(1);
    fireEvent.click(within(geometry).getByRole("button", { name: "Thử lại Tạo mesh" }));
    await waitFor(() => expect(buildObjectGeometry).toHaveBeenCalledWith("job-1", "rev-001"));
  });

  it("Ready: hàng xong, không có nút; Dựng lại vùng lỗi thì có Mở Studio và nêu scene giữ bản trước", async () => {
    renderTab(objectify({ object_geometry: "ready", status: "done" }));
    const geometry = await rowOf(GEOMETRY_ROW);
    expect(within(geometry).queryByRole("button")).toBeNull();
  });

  it("Ready, dựng lại vùng lỗi: Mở Studio và thông báo scene giữ bản trước", async () => {
    renderTab(objectify({ object_geometry: "ready", status: "failed", mode: "region", error: "vùng không hợp lệ" }), {
      onOpenStudio: vi.fn(),
    });
    const geometry = await rowOf(GEOMETRY_ROW);
    expect(await within(geometry).findByText(/Dựng lại vùng thất bại; scene giữ bản trước/)).toBeInTheDocument();
    expect(within(geometry).getByRole("button", { name: "Mở Studio" })).toBeInTheDocument();
  });

  it("scene cũ không có khoá object_geometry: không có hàng", async () => {
    renderTab(objectify({ object_geometry: null }));
    await waitFor(() => expect(getObjectifyState).toHaveBeenCalled());
    expect(screen.queryByText(GEOMETRY_ROW)).toBeNull();
  });

  it("người không có quyền sửa job thấy chữ nhưng không có nút", async () => {
    renderTab(objectify({ status: "failed", mode: "geometry", base_revision: "rev-001", error: "lỗi" }), {
      canAccept: false,
      onOpenStudio: vi.fn(),
    });
    const geometry = await rowOf(GEOMETRY_ROW);
    expect(await within(geometry).findByText("lỗi")).toBeInTheDocument();
    expect(within(geometry).queryByRole("button")).toBeNull();
  });
});
