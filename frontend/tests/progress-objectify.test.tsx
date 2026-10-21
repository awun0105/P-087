/** Bước "Tách vật thể" lỗi (tách theo vật hết số lần thử) phải báo lỗi và cho chọn tiếp ngay tại hàng bước ở tab Tiến trình. */
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import { ObjectifyContext } from "@/features/studio/scene/objectifyContext";
import { useObjectifyState } from "@/features/studio/scene/useObjectify";
import { ObjectifyNotice } from "@/features/studio/ObjectifyNotice";
import { ApiError } from "@/lib/api/client";
import { STUDIO_STAGES } from "@/features/studio/stages";
import { buildObjectGeometry, cancelObjectify, getObjectifyState, requestObjectify, type ObjectifyState } from "@/lib/api/studio";
import type { JobProgress } from "@/lib/contracts/studio";

vi.mock("@/features/studio/scene/AttemptHistory", () => ({ AttemptHistory: () => <div /> }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getObjectifyState: vi.fn(), requestObjectify: vi.fn(), cancelObjectify: vi.fn(), buildObjectGeometry: vi.fn(),
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
    expect(await within(row()).findByRole("alert")).toHaveTextContent("Tách theo vật không thành công");
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
  it("lỗi dữ liệu không báo có thể thử lại và vẫn cho chọn đường hộp", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue({ ...failed, retryable: false, note: "độ nhiễu 6.53 cm vượt ngưỡng 3.00 cm" });
    render(<SharedPage />);
    expect(await within(row()).findByRole("alert")).toHaveTextContent("dữ liệu chưa đạt điều kiện");
    expect(screen.queryByText("Có thể thử lại")).toBeNull();
    expect(screen.queryByRole("button", { name: "Chạy lại tách theo vật" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Dùng hộp ứng viên" })).toHaveLength(2);
    expect(screen.queryByText(/không thành công sau 3 lần thử/)).toBeNull();
  });
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
      const { result } = renderHook(() => useObjectifyState({ jobId: "job-1", onRevision }));
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

function SharedPage({ onRevision }: { onRevision?: (revision: string) => void }) {
  // Giống ScenePage: giữ một trạng thái duy nhất và chia sẻ cho tab Tiến trình lẫn thông báo trong Studio.
  const objectify = useObjectifyState({ jobId: "job-1", onRevision });
  return (
    <ObjectifyContext.Provider value={objectify}>
      <ProgressTab jobId="job-1" progress={done} info={null} busy={false} canCancel={false} canAccept onCancel={vi.fn()} />
      <ObjectifyNotice jobId="job-1" revision="rev-001" onRevision={vi.fn()} />
    </ObjectifyContext.Provider>
  );
}

describe("một trạng thái dùng chung trong trang scene", () => {
  it("thao tác ở hàng bước làm thông báo trong Studio đổi theo ngay, không gọi API đọc thêm", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(failed);
    vi.mocked(requestObjectify).mockResolvedValue(objectify({ status: "queued", mode: "boxes", object_centric: false, awaiting_choice: true }));
    render(<SharedPage />);
    // Cả hai nơi cùng báo lỗi từ một lần đọc.
    expect(await within(row()).findByRole("alert")).toBeInTheDocument();
    expect(screen.getAllByText(/Tách theo vật không thành công/).length).toBeGreaterThanOrEqual(2);
    expect(getObjectifyState).toHaveBeenCalledTimes(1);

    fireEvent.click(within(row()).getByRole("button", { name: "Dùng hộp ứng viên" }));
    // Thông báo trong Studio đổi sang "đang dựng" cùng lúc, không còn nút cũ gây 409.
    expect(await screen.findByText(/Đang dựng hộp ứng viên/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Hủy yêu cầu" }).length).toBe(2);
    expect(screen.queryAllByRole("button", { name: "Dùng hộp ứng viên" })).toHaveLength(0);
    expect(getObjectifyState).toHaveBeenCalledTimes(1);
  });
});

describe("nhãn đầu trang scene khi đang chạy lại", () => {
  it("hiện 'Cần chọn cách tách vật thể' khi chờ chọn, và quay về trạng thái job khi đã gửi yêu cầu chạy lại", async () => {
    const { progressSceneStatus } = await import("@/features/studio/sceneStatus");
    expect(progressSceneStatus(done, true)).toMatchObject({ label: "Cần chọn cách tách vật thể", group: "action" });
    expect(progressSceneStatus(done, false)).toMatchObject({ label: "Đã dựng scene", group: "done" });
    // Job chưa xong thì giữ nhãn pipeline dù scene đang chờ chọn.
    expect(progressSceneStatus({ ...done, status: "RUNNING" }, true).group).toBe("running");
  });
});

describe("thông báo tạo mesh theo vật (T-013)", () => {
  it("đang tạo mesh hiện nhãn phase tiếng Việt, và huỷ đúng operation_id của yêu cầu đang hiện", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "running", mode: "geometry", phase: "collider", operation_id: "op-7" }));
    vi.mocked(cancelObjectify).mockResolvedValue(objectify({ status: "running", mode: "geometry", phase: "collider", operation_id: "op-7", cancellation_requested: true }));
    render(<ObjectifyNotice jobId="job-1" revision="rev-001" onRevision={vi.fn()} />);

    expect(await screen.findByText(/Đang tạo mesh · Tạo collider/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hủy yêu cầu" }));
    await waitFor(() => expect(cancelObjectify).toHaveBeenCalledWith("job-1", "op-7"));
  });

  it("tạo mesh thất bại báo lỗi, và Thử lại gửi lại đúng revision đang hiển thị", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "failed", mode: "geometry", error: "vỏ rỗng ở Kệ" }));
    vi.mocked(buildObjectGeometry).mockResolvedValue(objectify({ status: "queued", mode: "geometry", operation_id: "op-8" }));
    render(<ObjectifyNotice jobId="job-1" revision="rev-001" onRevision={vi.fn()} />);

    expect(await screen.findByText(/Tạo mesh thất bại\. Scene duyệt được giữ nguyên\. vỏ rỗng ở Kệ/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(buildObjectGeometry).toHaveBeenCalledWith("job-1", "rev-001"));
  });

  it("tạo mesh đã huỷ không còn nút hủy", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "cancelled", mode: "geometry" }));
    render(<ObjectifyNotice jobId="job-1" revision="rev-001" onRevision={vi.fn()} />);

    expect(await screen.findByText(/Tạo mesh đã huỷ\. Scene duyệt được giữ nguyên\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy yêu cầu" })).toBeNull();
  });

  it("áp vùng thất bại chỉ báo lỗi, không có Thử lại vì vùng sửa ở Region Editor", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "failed", mode: "region", error: "box ngoài sàn" }));
    render(<ObjectifyNotice jobId="job-1" revision="rev-001" onRevision={vi.fn()} />);

    expect(await screen.findByText(/Áp vùng thất bại\. Scene hiện tại được giữ nguyên\. box ngoài sàn/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
  });

  const buildModes = ["geometry", "region", "membership"] as const;
  const outcomes = ["failed", "cancelled"] as const;

  it.each(buildModes.flatMap((mode) => outcomes.map((status) => ({ mode, status }))))(
    "keeps $mode $status visible only while viewing its base revision",
    async ({ mode, status }) => {
      vi.mocked(getObjectifyState).mockResolvedValue(objectify({
        status, mode, base_revision: "rev-121", scene_revision: "rev-121", error: "build outcome",
      }));
      const { rerender } = render(<ObjectifyNotice jobId="job-1" revision="rev-121" onRevision={vi.fn()} />);
      expect(await screen.findByRole("alert")).toHaveTextContent("build outcome");

      // Restore advances the displayed revision before the shared status request returns.
      rerender(<ObjectifyNotice jobId="job-1" revision="rev-122" onRevision={vi.fn()} />);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
    },
  );

  it.each(buildModes.flatMap((mode) => outcomes.map((status) => ({ mode, status }))))(
    "does not attach an old $mode $status to a restored scene on a fresh page load",
    async ({ mode, status }) => {
      vi.mocked(getObjectifyState).mockResolvedValue(objectify({
        status, mode, base_revision: "rev-121", scene_revision: "rev-122",
        error: "scene đã đổi sang rev-122 sau khi yêu cầu; yêu cầu lại nếu vẫn cần",
      }));
      await act(async () => {
        render(<ObjectifyNotice jobId="job-1" revision="rev-122" onRevision={vi.fn()} />);
      });
      expect(getObjectifyState).toHaveBeenCalled();
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
    },
  );

  it("waits for the displayed scene to catch up before showing an outcome from a newer revision", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({
      status: "failed", mode: "region", base_revision: "rev-122", scene_revision: "rev-122", error: "new build failed",
    }));
    const { rerender } = await act(async () => render(<ObjectifyNotice jobId="job-1" revision="rev-121" onRevision={vi.fn()} />));
    expect(screen.queryByRole("alert")).toBeNull();
    rerender(<ObjectifyNotice jobId="job-1" revision="rev-122" onRevision={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("new build failed");
  });

  it.each(["queued", "running"] as const)("keeps cancellation available for $status work after restore", async (status) => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({
      status, mode: "region", base_revision: "rev-121", scene_revision: "rev-122", operation_id: "old-region",
    }));
    vi.mocked(cancelObjectify).mockResolvedValue(objectify({
      status: "cancelled", mode: "region", base_revision: "rev-121", scene_revision: "rev-122", operation_id: "old-region",
    }));
    render(<ObjectifyNotice jobId="job-1" revision="rev-122" onRevision={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Hủy yêu cầu" }));
    await waitFor(() => expect(cancelObjectify).toHaveBeenCalledWith("job-1", "old-region"));
  });
});

describe("dòng kết quả thật trong tab Tiến trình", () => {
  it("truyền note máy chủ vào hàng bước và giữ tương thích khi thiếu note", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify());
    const progress: JobProgress = {...done, stages: done.stages.map((stage) => ({...stage, note: stage.stage_id === "ST-RGB-GEOMETRY" ? "Lưới từ LiDAR" : undefined}))};
    render(<ProgressTab jobId="job-1" progress={progress} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText("Lưới từ LiDAR")).toBeInTheDocument();
    await waitFor(() => expect(getObjectifyState).toHaveBeenCalled());
  });
  it("hiện số vật dùng ObjectGS và cách cũ ở hàng Duyệt vật", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({object_geometry: "ready", geometry_note: "2 vật dùng bề mặt ObjectGS; 3 vật dùng cách cũ (vỏ Gaussian)"}));
    renderTab();
    expect(await screen.findByText("2 vật dùng bề mặt ObjectGS; 3 vật dùng cách cũ (vỏ Gaussian)")).toBeInTheDocument();
  });
});
