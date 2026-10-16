/** Header scene: mốc gốc (đặt/bỏ/khôi phục) và "Đặt làm bản demo" xuất vào thư viện mẫu. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoControls } from "@/features/studio/scene/DemoControls";
import { clearDemo, getDemoState, markDemo, publishDemo, resetDemo, restoreRoot, removeSample } from "@/lib/api/studio";
import type { DemoState } from "@/lib/contracts/studio";

const auth: { me: { auth_required: boolean; user: { user_id: string; display_name: string; role: string } | null } } = {
  me: { auth_required: true, user: { user_id: "u1", display_name: "Editor", role: "editor" } },
};
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("@/lib/api/studio", () => ({
  getDemoState: vi.fn(), markDemo: vi.fn(), clearDemo: vi.fn(), resetDemo: vi.fn(), restoreRoot: vi.fn(), publishDemo: vi.fn(), removeSample: vi.fn(),
}));

const baseline = { job_id: "job-a", scene_revision: "rev-001", marked_at: "2026-10-03T00:00:00Z" };
function demo(current: string, atBaseline: boolean, marked = true, published: string | null = null, atRoot = false): DemoState {
  return { job_id: "job-a", baseline: marked ? baseline : null, current_revision: current, at_baseline: atBaseline, at_root: atRoot, published_sample_id: published };
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Editor", role: "editor" } };
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("DemoControls: mốc gốc", () => {
  it("keeps only publication controls on the header", async () => {
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-003", false, true, "room-sample"));
    render(<DemoControls scope="publication" jobId="job-a" revision="rev-003" sceneReady onRestored={vi.fn()} />);
    expect(await screen.findByRole("link", { name: "Đã có trong thư viện mẫu" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Về bản gốc" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Quay lại trạng thái đã lưu" })).toBeNull();
  });

  it("shows state information in the panel without publication controls", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-003", false, true, "room-sample", true));
    render(<DemoControls scope="state" jobId="job-a" revision="rev-003" sceneReady onRestored={vi.fn()} />);
    expect(await screen.findByText("Đang ở bản gốc")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lưu trạng thái" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quay lại trạng thái đã lưu" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Về bản gốc" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bỏ trạng thái đã lưu" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Đã có trong thư viện mẫu" })).toBeNull();
    expect(screen.getByText(/Đã lưu lúc/)).toBeInTheDocument();
  });
  it("Editor có thể về bản gốc ngay cả khi chưa lưu trạng thái", async () => {
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={vi.fn()} />);
    await waitFor(() => expect(getDemoState).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Về bản gốc" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lưu trạng thái" })).toBeNull();
  });

  it("khôi phục gửi revision đang thấy và báo revision mới cho Studio", async () => {
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-004", false));
    vi.mocked(resetDemo).mockResolvedValue(demo("rev-005", true));
    const restored = vi.fn();
    render(<DemoControls jobId="job-a" revision="rev-004" sceneReady onRestored={restored} />);
    expect(await screen.findByText("Có trạng thái đã lưu")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Quay lại trạng thái đã lưu" }));
    await waitFor(() => expect(restored).toHaveBeenCalledWith("rev-005"));
    expect(resetDemo).toHaveBeenCalledWith("job-a", "rev-004");
    expect(screen.getByRole("button", { name: "Quay lại trạng thái đã lưu" })).toBeDisabled();
  });

  it("Reviewer đặt và bỏ mốc gốc; Editor không có hai nút này", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    vi.mocked(markDemo).mockResolvedValue(demo("rev-002", true));
    vi.mocked(clearDemo).mockResolvedValue(demo("rev-002", false, false));
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Lưu trạng thái" }));
    expect(await screen.findByRole("button", { name: "Bỏ trạng thái đã lưu" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bỏ trạng thái đã lưu" }));
    await waitFor(() => expect(clearDemo).toHaveBeenCalledWith("job-a"));
  });

  it("Reviewer thấy nút 'Về bản gốc' kế nút 'Lưu trạng thái', bấm về bản gốc gọi restoreRoot", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false, null, false));
    vi.mocked(restoreRoot).mockResolvedValue(demo("rev-003", false, false, null, true));
    const restored = vi.fn();
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={restored} />);
    expect(await screen.findByRole("button", { name: "Lưu trạng thái" })).toBeInTheDocument();
    const btnRoot = screen.getByRole("button", { name: "Về bản gốc" });
    expect(btnRoot).toBeInTheDocument();
    fireEvent.click(btnRoot);
    await waitFor(() => expect(restoreRoot).toHaveBeenCalledWith("job-a", "rev-002"));
    expect(restored).toHaveBeenCalledWith("rev-003");
  });

  it("khi đang ở bản gốc (at_root=true), nút Về bản gốc chuyển thành Về bản gốc và bị disable, nhưng có mốc đã lưu thì Quay lại trạng thái đã lưu vẫn bấm được", async () => {
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-003", false, true, null, true));
    vi.mocked(resetDemo).mockResolvedValue(demo("rev-004", true, true, null, false));
    const restored = vi.fn();
    render(<DemoControls jobId="job-a" revision="rev-003" sceneReady onRestored={restored} />);
    expect(await screen.findByText("Có trạng thái đã lưu")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Về bản gốc" })).toBeDisabled();
    const btnRestoreBaseline = screen.getByRole("button", { name: "Quay lại trạng thái đã lưu" });
    expect(btnRestoreBaseline).not.toBeDisabled();
    fireEvent.click(btnRestoreBaseline);
    await waitFor(() => expect(resetDemo).toHaveBeenCalledWith("job-a", "rev-003"));
    expect(restored).toHaveBeenCalledWith("rev-004");
  });

  it("scene chưa dựng xong thì không hỏi trạng thái demo", () => {
    render(<DemoControls jobId="job-a" revision={null} sceneReady={false} onRestored={vi.fn()} />);
    expect(getDemoState).not.toHaveBeenCalled();
  });

  it("Reviewer can replace a saved state while viewing the original", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-003", false, true, null, true));
    vi.mocked(markDemo).mockResolvedValue(demo("rev-003", true, true, null, true));
    render(<DemoControls jobId="job-a" revision="rev-003" sceneReady onRestored={vi.fn()} />);
    const save = await screen.findByRole("button", { name: "Lưu trạng thái" });
    expect(save).not.toBeDisabled();
    fireEvent.click(save);
    await waitFor(() => expect(markDemo).toHaveBeenCalledWith("job-a"));
    expect(screen.getByRole("button", { name: "Quay lại trạng thái đã lưu" })).toBeDisabled();
    expect(restoreRoot).not.toHaveBeenCalled();
  });
});

describe("DemoControls: Đặt làm bản demo = xuất vào thư viện mẫu", () => {
  it("Reviewer phải xác nhận công khai mới xuất được, và gửi tên + mô tả", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    vi.mocked(publishDemo).mockResolvedValue({ sample_id: "kho-a-1234", title: "Kho A" });
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady defaultTitle="Kho A" onRestored={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Đặt làm bản demo" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Tên mẫu")).toHaveValue("Kho A");
    const submit = within(dialog).getByRole("button", { name: "Xuất vào thư viện mẫu" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Mô tả (tuỳ chọn)"), { target: { value: " Lối đi chính " } });
    fireEvent.click(within(dialog).getByRole("checkbox"));
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() => expect(publishDemo).toHaveBeenCalledWith("job-a", { title: "Kho A", description: "Lối đi chính", confirm_public: true }));
    const link = await screen.findByRole("link", { name: "Đã có trong thư viện mẫu" });
    expect(link).toHaveAttribute("href", "/new/try-demo?sample=kho-a-1234");
    expect(screen.queryByRole("button", { name: "Đặt làm bản demo" })).toBeNull();
  });

  it("lỗi từ máy chủ hiện ngay trong hộp thoại và không đánh dấu đã xuất", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    vi.mocked(publishDemo).mockRejectedValue(new Error("Chỉ công khai được scene đã xác nhận quyền sử dụng và đã ẩn danh khi tạo"));
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady defaultTitle="Kho A" onRestored={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Đặt làm bản demo" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Xuất vào thư viện mẫu" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("đã ẩn danh");
    expect(screen.queryByRole("link", { name: "Đã có trong thư viện mẫu" })).toBeNull();
  });

  it("Editor không có nút xuất; mẫu đã xuất thì ai cũng thấy đường dẫn", async () => {
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    const first = render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={vi.fn()} />);
    await waitFor(() => expect(getDemoState).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Về bản gốc" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Đặt làm bản demo" })).toBeNull();
    first.unmount();

    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false, "kho-a-1234"));
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={vi.fn()} />);
    expect(await screen.findByRole("link", { name: "Đã có trong thư viện mẫu" })).toHaveAttribute("href", "/new/try-demo?sample=kho-a-1234");
    expect(screen.queryByRole("button", { name: "Đặt làm bản demo" })).toBeNull();
  });

  it("tắt đăng nhập: không có nút xuất (cần Reviewer thật) dù vẫn đặt được mốc gốc", async () => {
    auth.me = { auth_required: false, user: null };
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Lưu trạng thái" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Đặt làm bản demo" })).toBeNull();
  });

  it("người khác vừa xuất cùng scene: báo lỗi rồi đọc lại và chuyển nút thành đường dẫn tới mẫu", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
    vi.mocked(getDemoState).mockResolvedValueOnce(demo("rev-002", false, false)).mockResolvedValue(demo("rev-002", false, false, "kho-a-1234"));
    vi.mocked(publishDemo).mockRejectedValue(new Error("Job này đã có trong thư viện mẫu (kho-a-1234)"));
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady defaultTitle="Kho A" onRestored={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Đặt làm bản demo" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Xuất vào thư viện mẫu" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("đã có trong thư viện mẫu");
    await waitFor(() => expect(getDemoState).toHaveBeenCalledTimes(2));
  });
});


it("Reviewer gỡ mẫu công khai mà không bỏ trạng thái đã lưu của dự án", async () => {
  auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
  vi.mocked(getDemoState).mockResolvedValue(demo("rev-003", false, true, "room-sample"));
  vi.mocked(removeSample).mockRejectedValueOnce(new Error("Chưa gỡ được")).mockResolvedValueOnce(undefined);
  render(<DemoControls jobId="job-a" revision="rev-003" sceneReady onRestored={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Bỏ khỏi demo" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Chưa gỡ được");
  expect(screen.getByRole("link", { name: "Đã có trong thư viện mẫu" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Bỏ khỏi demo" }));
  await screen.findByRole("button", { name: "Đặt làm bản demo" });
  expect(removeSample).toHaveBeenCalledWith("room-sample");
  expect(clearDemo).not.toHaveBeenCalled();
  expect(screen.getByText("Có trạng thái đã lưu")).toBeInTheDocument();
});
