import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GpuStartupNotice, formatWait, startupProgress } from "@/features/studio/GpuStartupNotice";
import type { GpuCapacity } from "@/lib/api/gpu";

const NOW = Date.parse("2026-10-20T05:00:00Z");

function capacity(overrides: Partial<GpuCapacity>): GpuCapacity {
  return {
    state: "off",
    since: null,
    elapsed_seconds: null,
    expected_startup_seconds: 900,
    remaining_seconds: null,
    sample_count: 0,
    ...overrides,
  };
}

describe("GpuStartupNotice", () => {
  it("rounds waits up so they are never understated", () => {
    expect(formatWait(30)).toBe("dưới 1 phút");
    expect(formatWait(61)).toBe("khoảng 2 phút");
    expect(formatWait(900)).toBe("khoảng 15 phút");
  });

  it("counts down locally from since instead of the server snapshot", () => {
    const started = capacity({ state: "starting", since: "2026-10-20T04:55:00Z", elapsed_seconds: 1, remaining_seconds: 899 });
    expect(startupProgress(started, NOW)).toEqual({ elapsed: 300, remaining: 600, ratio: 300 / 900 });
  });

  it("explains a cold start with remaining time and a progress bar", () => {
    render(<GpuStartupNotice capacity={capacity({ state: "starting", since: "2026-10-20T04:55:00Z" })} now={NOW} />);
    expect(screen.getByText("Đang khởi động máy GPU")).toBeInTheDocument();
    expect(screen.getByText(/Còn khoảng 10 phút/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Tiến độ khởi động máy GPU" })).toHaveAttribute("aria-valuenow", "33");
  });

  it("says it is almost done once the typical startup has passed", () => {
    render(<GpuStartupNotice capacity={capacity({ state: "starting", since: "2026-10-20T04:30:00Z" })} now={NOW} />);
    expect(screen.getByText(/Sắp xong/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("tells the user a stopped GPU will start automatically and how long that takes", () => {
    render(<GpuStartupNotice capacity={capacity({ state: "off", expected_startup_seconds: 720 })} now={NOW} />);
    expect(screen.getByText(/tự bật, thường mất khoảng 12 phút/)).toBeInTheDocument();
  });

  it("flags a blocked GPU as an alert for the administrator", () => {
    render(<GpuStartupNotice capacity={capacity({ state: "blocked" })} now={NOW} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Chưa có máy GPU");
  });

  it("renders nothing when the GPU is ready, unmanaged, or unknown", () => {
    const { container, rerender } = render(<GpuStartupNotice capacity={capacity({ state: "ready" })} now={NOW} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<GpuStartupNotice capacity={capacity({ state: "unmanaged" })} now={NOW} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<GpuStartupNotice capacity={null} now={NOW} />);
    expect(container).toBeEmptyDOMElement();
  });
});
