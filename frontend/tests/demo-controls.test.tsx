/** Header scene: mốc gốc (đặt/bỏ/khôi phục) và "Đặt làm bản demo" xuất vào thư viện mẫu. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoControls } from "@/features/studio/scene/DemoControls";
import { clearDemo, getDemoState, markDemo, publishDemo, resetDemo } from "@/lib/api/studio";
import type { DemoState } from "@/lib/contracts/studio";

const auth: { me: { auth_required: boolean; user: { user_id: string; display_name: string; role: string } | null } } = {
  me: { auth_required: true, user: { user_id: "u1", display_name: "Editor", role: "editor" } },
};
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("@/lib/api/studio", () => ({
  getDemoState: vi.fn(), markDemo: vi.fn(), clearDemo: vi.fn(), resetDemo: vi.fn(), publishDemo: vi.fn(),
}));

const baseline = { job_id: "job-a", scene_revision: "rev-001", marked_at: "2026-10-03T00:00:00Z" };
function demo(current: string, atBaseline: boolean, marked = true, published: string | null = null): DemoState {
  return { job_id: "job-a", baseline: marked ? baseline : null, current_revision: current, at_baseline: atBaseline, published_sample_id: published };
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Editor", role: "editor" } };
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("DemoControls: mốc gốc", () => {
  it("scene chưa có mốc gốc và chưa xuất: Editor không thấy gì", async () => {
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    const { container } = render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={vi.fn()} />);
    await waitFor(() => expect(getDemoState).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("khôi phục gửi revision đang thấy và báo revision mới cho Studio", async () => {
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-004", false));
    vi.mocked(resetDemo).mockResolvedValue(demo("rev-005", true));
    const restored = vi.fn();
    render(<DemoControls jobId="job-a" revision="rev-004" sceneReady onRestored={restored} />);
    expect(await screen.findByText("Có mốc gốc")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục về mốc gốc" }));
    await waitFor(() => expect(restored).toHaveBeenCalledWith("rev-005"));
    expect(resetDemo).toHaveBeenCalledWith("job-a", "rev-004");
    expect(screen.getByRole("button", { name: "Đang ở mốc gốc" })).toBeDisabled();
  });

  it("Reviewer đặt và bỏ mốc gốc; Editor không có hai nút này", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", display_name: "Reviewer", role: "reviewer" } };
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    vi.mocked(markDemo).mockResolvedValue(demo("rev-002", true));
    vi.mocked(clearDemo).mockResolvedValue(demo("rev-002", false, false));
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Đặt mốc gốc" }));
    expect(await screen.findByRole("button", { name: "Bỏ mốc gốc" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bỏ mốc gốc" }));
    await waitFor(() => expect(clearDemo).toHaveBeenCalledWith("job-a"));
  });

  it("scene chưa dựng xong thì không hỏi trạng thái demo", () => {
    render(<DemoControls jobId="job-a" revision={null} sceneReady={false} onRestored={vi.fn()} />);
    expect(getDemoState).not.toHaveBeenCalled();
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
    expect(first.container).toBeEmptyDOMElement();
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
    expect(await screen.findByRole("button", { name: "Đặt mốc gốc" })).toBeInTheDocument();
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
