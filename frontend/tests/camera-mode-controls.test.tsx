import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CameraModeControls } from "@/features/viewer/CameraModeControls";
import { INITIAL_RUNTIME, type ViewerControls } from "@/features/viewer/PlayCanvasScene";

function mockControls(overrides?: Partial<ViewerControls>): ViewerControls {
  return {
    select: vi.fn(() => true),
    setInputEnabled: vi.fn(),
    setCameraMode: vi.fn(() => true),
    frameScene: vi.fn(() => true),
    resetCamera: vi.fn(() => true),
    ...overrides,
  };
}

describe("CameraModeControls", () => {
  it("hiển thị 3 nút chế độ và highlight chế độ hiện tại", () => {
    const controls = mockControls();
    render(
      <CameraModeControls
        runtime={{ ...INITIAL_RUNTIME, loaded: true, cameraMode: "fly" }}
        controls={controls}
      />,
    );

    const orbitBtn = screen.getByRole("button", { name: /Xoay/ });
    const flyBtn = screen.getByRole("button", { name: /Bay/ });
    const walkBtn = screen.getByRole("button", { name: /Đi bộ/ });

    expect(orbitBtn).toHaveAttribute("aria-pressed", "false");
    expect(flyBtn).toHaveAttribute("aria-pressed", "true");
    expect(walkBtn).toBeDisabled(); // chưa có va chạm (walkAllowed = false)
  });

  it("cho phép chuyển sang đi bộ khi walkAllowed = true", () => {
    const controls = mockControls();
    render(
      <CameraModeControls
        runtime={{ ...INITIAL_RUNTIME, loaded: true, walkAllowed: true, cameraMode: "orbit" }}
        controls={controls}
      />,
    );

    const walkBtn = screen.getByRole("button", { name: /Đi bộ/ });
    expect(walkBtn).not.toBeDisabled();
    fireEvent.click(walkBtn);
    expect(controls.setCameraMode).toHaveBeenCalledWith("walk");
  });

  it("chuyển sang fly khi bấm nút Bay", () => {
    const controls = mockControls();
    render(
      <CameraModeControls
        runtime={{ ...INITIAL_RUNTIME, loaded: true, cameraMode: "orbit" }}
        controls={controls}
      />,
    );

    const flyBtn = screen.getByRole("button", { name: /Bay/ });
    fireEvent.click(flyBtn);
    expect(controls.setCameraMode).toHaveBeenCalledWith("fly");
  });
});
