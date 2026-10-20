import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ObjectifyContext } from "@/features/studio/scene/objectifyContext";
import { ObjectifyNotice } from "@/features/studio/ObjectifyNotice";

describe("Studio notice uses the shared operation wording (T-062)", () => {
  it("says 'Đang dựng lại vùng' for a region rebuild, like the header and the bell", () => {
    const handle = {
      state: { status: "running", mode: "region", phase: "shell", scene_revision: "rev-3", cancellation_requested: false },
      error: null, sending: false, pending: true, send: vi.fn(), cancel: vi.fn(), refresh: vi.fn(),
    } as never;
    render(<ObjectifyContext.Provider value={handle}><ObjectifyNotice jobId="job-1" revision="rev-3" onRevision={vi.fn()} /></ObjectifyContext.Provider>);
    expect(screen.getByText(/Đang dựng lại vùng · Dựng vỏ vật/)).toBeInTheDocument();
  });
});
