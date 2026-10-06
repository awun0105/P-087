/** Thanh điều khiển camera: trạng thái đọc từ viewer, lệnh đi qua API công khai của viewer. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CameraToolbar } from "@/features/viewer/CameraToolbar";
import { INITIAL_RUNTIME, scaledWheelInit, type PlayCanvasRuntime, type ViewerControls } from "@/features/viewer/PlayCanvasScene";

function controls(): ViewerControls {
  return {
    select: vi.fn(() => true),
    setInputEnabled: vi.fn(),
    setCameraMode: vi.fn(() => true),
    frameScene: vi.fn(() => true),
    resetCamera: vi.fn(() => true),
    playTrajectory: vi.fn(() => true),
    pauseTrajectory: vi.fn(() => true),
    seekTrajectory: vi.fn(() => true),
  };
}
const loaded: PlayCanvasRuntime = { ...INITIAL_RUNTIME, loaded: true, progress: 100 };

describe("CameraToolbar", () => {
  it("khoá mọi nút khi viewer chưa nạp xong", () => {
    render(<CameraToolbar runtime={INITIAL_RUNTIME} controls={controls()} wheelFactor={1} onWheelFactor={vi.fn()} />);
    for (const name of ["Xoay", "Bay", "Đi bộ", "Toàn cảnh", "Về vị trí đầu"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("chuyển chế độ, về toàn cảnh và về vị trí đầu qua controls của viewer", () => {
    const api = controls();
    render(<CameraToolbar runtime={{ ...loaded, hasCollision: true, walkAllowed: true }} controls={api} wheelFactor={1} onWheelFactor={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Xoay" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Bay" }));
    fireEvent.click(screen.getByRole("button", { name: "Đi bộ" }));
    expect(vi.mocked(api.setCameraMode).mock.calls).toEqual([["fly"], ["walk"]]);
    fireEvent.click(screen.getByRole("button", { name: "Toàn cảnh" }));
    fireEvent.click(screen.getByRole("button", { name: "Về vị trí đầu" }));
    expect(api.frameScene).toHaveBeenCalledOnce();
    expect(api.resetCamera).toHaveBeenCalledOnce();
  });

  it("không cho đi bộ khi viewer báo chưa có va chạm, và hiện hướng dẫn theo chế độ đang chạy", () => {
    const api = controls();
    const { rerender } = render(<CameraToolbar runtime={loaded} controls={api} wheelFactor={1} onWheelFactor={vi.fn()} />);
    const walk = screen.getByRole("button", { name: "Đi bộ" });
    expect(walk).toBeDisabled();
    expect(walk).toHaveAttribute("title", expect.stringContaining("lưới va chạm"));
    expect(screen.getByText(/bấm đúp một điểm/)).toBeInTheDocument();
    rerender(<CameraToolbar runtime={{ ...loaded, walkAllowed: true, cameraMode: "walk" }} controls={api} wheelFactor={1} onWheelFactor={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Đi bộ" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/bị tường và vật thể chặn lại/)).toBeInTheDocument();
  });

  it("đổi tốc độ zoom", () => {
    const change = vi.fn();
    render(<CameraToolbar runtime={loaded} controls={controls()} wheelFactor={2} onWheelFactor={change} />);
    fireEvent.change(screen.getByLabelText("Tốc độ zoom"), { target: { value: "4" } });
    expect(change).toHaveBeenCalledWith(4);
  });
});

describe("scaledWheelInit", () => {
  it("nhân bước cuộn, giữ vị trí con trỏ và phím bổ trợ", () => {
    const event = new WheelEvent("wheel", { deltaY: 100, deltaX: -4, clientX: 30, clientY: 40, ctrlKey: true, deltaMode: 1 });
    const init = scaledWheelInit(event, 4);
    expect(init).toMatchObject({ deltaY: 400, deltaX: -16, clientX: 30, clientY: 40, ctrlKey: true, deltaMode: 1, bubbles: true, cancelable: true });
  });

  it("góc nhìn thứ ba chỉ bật được khi đang đi bộ", () => {
    const toggle = vi.fn();
    const { rerender } = render(
      <CameraToolbar runtime={loaded} controls={controls()} wheelFactor={1} onWheelFactor={vi.fn()} thirdPerson={false} onThirdPerson={toggle} />,
    );
    expect(screen.getByRole("button", { name: "Góc nhìn thứ ba" })).toBeDisabled();
    rerender(
      <CameraToolbar runtime={{ ...loaded, walkAllowed: true, cameraMode: "walk" }} controls={controls()} wheelFactor={1} onWheelFactor={vi.fn()} thirdPerson={false} onThirdPerson={toggle} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Góc nhìn thứ ba" }));
    expect(toggle).toHaveBeenCalledWith(true);
  });

  it("viewer không hỗ trợ góc nhìn thứ ba thì không có nút", () => {
    render(<CameraToolbar runtime={loaded} controls={controls()} wheelFactor={1} onWheelFactor={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Góc nhìn thứ ba" })).toBeNull();
  });
});
