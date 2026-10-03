/** Bản demo trên header scene: khôi phục về mốc gốc, Reviewer đánh dấu/bỏ đánh dấu. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoControls } from "@/features/studio/scene/DemoControls";
import { clearDemo, getDemoState, markDemo, resetDemo } from "@/lib/api/studio";
import type { DemoState } from "@/lib/contracts/studio";

const auth = { me: { auth_required: true, user: { user_id: "u1", display_name: "Editor", role: "editor" } } };
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("@/lib/api/studio", () => ({ getDemoState: vi.fn(), markDemo: vi.fn(), clearDemo: vi.fn(), resetDemo: vi.fn() }));

const baseline = { job_id: "job-a", scene_revision: "rev-001", marked_at: "2026-10-03T00:00:00Z" };
function demo(current: string, atBaseline: boolean, marked = true): DemoState {
  return { job_id: "job-a", baseline: marked ? baseline : null, current_revision: current, at_baseline: atBaseline };
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.me.user.role = "editor";
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("DemoControls", () => {
  it("scene chưa phải bản demo: Editor không thấy gì", async () => {
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
    expect(await screen.findByText("Bản demo")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Khôi phục bản demo" }));
    await waitFor(() => expect(restored).toHaveBeenCalledWith("rev-005"));
    expect(resetDemo).toHaveBeenCalledWith("job-a", "rev-004");
    expect(screen.getByRole("button", { name: "Đang ở bản gốc" })).toBeDisabled();
  });

  it("Reviewer đánh dấu và bỏ đánh dấu; Editor không có hai nút này", async () => {
    auth.me.user.role = "reviewer";
    vi.mocked(getDemoState).mockResolvedValue(demo("rev-002", false, false));
    vi.mocked(markDemo).mockResolvedValue(demo("rev-002", true));
    vi.mocked(clearDemo).mockResolvedValue(demo("rev-002", false, false));
    render(<DemoControls jobId="job-a" revision="rev-002" sceneReady onRestored={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Đặt làm bản demo" }));
    expect(await screen.findByRole("button", { name: "Bỏ đánh dấu" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bỏ đánh dấu" }));
    await waitFor(() => expect(clearDemo).toHaveBeenCalledWith("job-a"));
  });

  it("scene chưa dựng xong thì không hỏi trạng thái demo", () => {
    render(<DemoControls jobId="job-a" revision={null} sceneReady={false} onRestored={vi.fn()} />);
    expect(getDemoState).not.toHaveBeenCalled();
  });
});
