/** Đồng hồ phút công người: luật rảnh 60 s, tab ẩn, lô không chồng và không vượt 300 s (architecture §15.3). */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperatorClock, MAX_BATCH_MS } from "@/features/studio/value/operator-clock";
import { useOperatorTime } from "@/features/studio/value/useOperatorTime";
import type { OperatorTimeBatch, OperatorTimeSurface } from "@/lib/api/value";

const post = vi.hoisted(() => vi.fn<(...args: unknown[]) => Promise<undefined>>(async () => undefined));
vi.mock("@/lib/api/value", () => ({ postOperatorTime: post }));

const T0 = Date.UTC(2026, 9, 16, 9, 0, 0);

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

function sent(): OperatorTimeBatch[] {
  return post.mock.calls.map((call) => call[1] as OperatorTimeBatch);
}

function ms(iso: string): number {
  return Date.parse(iso);
}

describe("OperatorClock", () => {
  it("counts ticks only within 60 s of the last activity", () => {
    const clock = new OperatorClock("session-1", "studio");
    clock.start(T0);
    clock.activity(T0);
    for (let t = 1; t <= 90; t++) clock.tick(T0 + t * 1000);
    const batch = clock.close(T0 + 90_000);
    expect(batch?.active_seconds).toBe(60);
  });

  it("caps one tick at 2 s so a frozen tab cannot add a long gap", () => {
    const clock = new OperatorClock("session-1", "studio");
    clock.start(T0);
    clock.activity(T0 + 10_000);
    clock.tick(T0 + 25_000);
    expect(clock.close(T0 + 25_000)?.active_seconds).toBe(2);
  });

  it("opens each window at the previous end and never exceeds 300 s", () => {
    const clock = new OperatorClock("session-1", "studio");
    clock.start(T0);
    let first: OperatorTimeBatch | null = null;
    let second: OperatorTimeBatch | null = null;
    for (let t = 1; t <= 400; t++) {
      clock.activity(T0 + t * 1000);
      clock.tick(T0 + t * 1000);
      if (t === 30) first = clock.cut(T0 + t * 1000);
      if (t === 400) second = clock.cut(T0 + t * 1000);
    }
    expect(first?.ended_at).toBe(new Date(T0 + 30_000).toISOString());
    expect(second?.started_at).toBe(first?.ended_at);
    expect(ms(second!.ended_at) - ms(second!.started_at)).toBeLessThanOrEqual(MAX_BATCH_MS);
  });

  it("returns no batch when nothing was active", () => {
    const clock = new OperatorClock("session-1", "studio");
    clock.start(T0);
    clock.tick(T0 + 1000);
    expect(clock.cut(T0 + 30_000)).toBeNull();
  });
});

describe("useOperatorTime", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: T0 });
    post.mockClear();
    setVisibility("visible");
  });

  afterEach(() => {
    setVisibility("visible");
    vi.useRealTimers();
  });

  it("sends nothing when the viewer cannot mutate the job", () => {
    const { unmount } = renderHook(() => useOperatorTime({ jobId: "job-1", surface: "studio", enabled: false }));
    act(() => {
      window.dispatchEvent(new Event("keydown"));
      vi.advanceTimersByTime(90_000);
    });
    unmount();
    expect(post).not.toHaveBeenCalled();
  });

  it("sends contiguous batches with the surface and a stable session key", () => {
    const { unmount } = renderHook(() => useOperatorTime({ jobId: "job-1", surface: "studio", enabled: true }));
    act(() => {
      for (let second = 0; second < 70; second++) {
        window.dispatchEvent(new Event("keydown"));
        vi.advanceTimersByTime(1000);
      }
    });
    unmount();

    const batches = sent();
    expect(batches.length).toBeGreaterThanOrEqual(2);
    expect(new Set(batches.map((item) => item.session_key)).size).toBe(1);
    expect(batches.every((item) => item.surface === "studio")).toBe(true);
    for (let index = 1; index < batches.length; index++) {
      expect(batches[index].started_at).toBe(batches[index - 1].ended_at);
    }
    for (const batch of batches) {
      const wall = (ms(batch.ended_at) - ms(batch.started_at)) / 1000;
      expect(wall).toBeLessThanOrEqual(300);
      expect(batch.active_seconds).toBeGreaterThan(0);
      expect(batch.active_seconds).toBeLessThanOrEqual(wall);
    }
  });

  it("does not count time after 60 s of idleness", () => {
    const { unmount } = renderHook(() => useOperatorTime({ jobId: "job-1", surface: "studio", enabled: true }));
    act(() => {
      window.dispatchEvent(new Event("keydown"));
      vi.advanceTimersByTime(100_000);
    });
    unmount();
    const total = sent().reduce((sum, batch) => sum + batch.active_seconds, 0);
    expect(total).toBe(60);
  });

  it("pauses while the tab is hidden and resumes when it is visible again", () => {
    const { unmount } = renderHook(() => useOperatorTime({ jobId: "job-1", surface: "progress", enabled: true }));
    act(() => {
      window.dispatchEvent(new Event("keydown"));
      vi.advanceTimersByTime(5000);
      setVisibility("hidden");
    });
    const flushedOnHide = sent();
    expect(flushedOnHide).toHaveLength(1);
    expect(flushedOnHide[0].active_seconds).toBe(5);

    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(sent()).toHaveLength(1);

    act(() => {
      setVisibility("visible");
      window.dispatchEvent(new Event("keydown"));
      vi.advanceTimersByTime(3000);
    });
    unmount();
    expect(sent().at(-1)?.active_seconds).toBe(3);
  });

  it("closes the old tab's batch before the new surface starts", () => {
    const { rerender, unmount } = renderHook(
      ({ surface }: { surface: OperatorTimeSurface }) => useOperatorTime({ jobId: "job-1", surface, enabled: true }),
      { initialProps: { surface: "progress" as OperatorTimeSurface } },
    );
    act(() => {
      window.dispatchEvent(new Event("keydown"));
      vi.advanceTimersByTime(4000);
    });
    rerender({ surface: "studio" });
    act(() => {
      window.dispatchEvent(new Event("keydown"));
      vi.advanceTimersByTime(2000);
    });
    unmount();

    const batches = sent();
    expect(batches.map((item) => item.surface)).toEqual(["progress", "studio"]);
    expect(batches[1].started_at).toBe(batches[0].ended_at);
  });

  it("sends the final batch on unmount and nothing when the pointer only hovers", () => {
    const { unmount } = renderHook(() => useOperatorTime({ jobId: "job-1", surface: "other", enabled: true }));
    act(() => {
      window.dispatchEvent(new PointerEvent("pointermove", { buttons: 0 }));
      vi.advanceTimersByTime(5000);
    });
    unmount();
    expect(post).not.toHaveBeenCalled();
  });
});
