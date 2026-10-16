/** Phiên Walk (architecture §15.3): bắt đầu khi bật, gửi khi tắt hoặc rời trang; hoàn tất từ 5 giây. */
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ValueTrackingContext, type ValueTracking } from "@/features/studio/value/tracking-context";
import { useWalkSession } from "@/features/studio/value/useWalkSession";
import type { WalkSessionBatch } from "@/lib/api/value";

const send = vi.hoisted(() => vi.fn<(...args: unknown[]) => Promise<undefined>>(async () => undefined));
vi.mock("@/lib/api/value", () => ({ postWalkSession: send }));

const T0 = Date.UTC(2026, 9, 16, 9, 0, 0);

function wrapper(tracking: ValueTracking) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <ValueTrackingContext.Provider value={tracking}>{children}</ValueTrackingContext.Provider>;
  };
}

function sent(): WalkSessionBatch[] {
  return send.mock.calls.map((call) => call[1] as WalkSessionBatch);
}

describe("useWalkSession", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: T0 });
    send.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends a completed session when Walk stays on for 5 seconds or more", () => {
    const { rerender, unmount } = renderHook(
      ({ walking }: { walking: boolean }) => useWalkSession({ walking, sceneRevision: "rev-002" }),
      { initialProps: { walking: false }, wrapper: wrapper({ jobId: "job-1", enabled: true }) },
    );
    rerender({ walking: true });
    vi.advanceTimersByTime(7000);
    rerender({ walking: false });
    unmount();

    expect(sent()).toEqual([
      {
        scene_revision: "rev-002",
        started_at: new Date(T0).toISOString(),
        ended_at: new Date(T0 + 7000).toISOString(),
        outcome: "completed",
      },
    ]);
    expect(send.mock.calls[0][0]).toBe("job-1");
  });

  it("marks a short Walk as aborted", () => {
    const { rerender, unmount } = renderHook(
      ({ walking }: { walking: boolean }) => useWalkSession({ walking, sceneRevision: "rev-002" }),
      { initialProps: { walking: false }, wrapper: wrapper({ jobId: "job-1", enabled: true }) },
    );
    rerender({ walking: true });
    vi.advanceTimersByTime(3000);
    rerender({ walking: false });
    unmount();

    expect(sent()[0].outcome).toBe("aborted");
  });

  it("sends the open session when the page is left", () => {
    const { rerender, unmount } = renderHook(
      ({ walking }: { walking: boolean }) => useWalkSession({ walking, sceneRevision: "rev-002" }),
      { initialProps: { walking: false }, wrapper: wrapper({ jobId: "job-1", enabled: true }) },
    );
    rerender({ walking: true });
    vi.advanceTimersByTime(6000);
    unmount();

    expect(sent()).toHaveLength(1);
    expect(sent()[0].outcome).toBe("completed");
  });

  it("does nothing for a viewer who cannot mutate, without a revision, or when Walk never started", () => {
    const denied = renderHook(() => useWalkSession({ walking: true, sceneRevision: "rev-002" }), {
      wrapper: wrapper({ jobId: "job-1", enabled: false }),
    });
    vi.advanceTimersByTime(6000);
    denied.unmount();

    const noRevision = renderHook(() => useWalkSession({ walking: true, sceneRevision: undefined }), {
      wrapper: wrapper({ jobId: "job-1", enabled: true }),
    });
    vi.advanceTimersByTime(6000);
    noRevision.unmount();

    const idle = renderHook(() => useWalkSession({ walking: false, sceneRevision: "rev-002" }), {
      wrapper: wrapper({ jobId: "job-1", enabled: true }),
    });
    idle.unmount();

    expect(send).not.toHaveBeenCalled();
  });

  it("closes the session on the old revision when the scene revision changes", () => {
    const { rerender, unmount } = renderHook(
      ({ revision }: { revision: string }) => useWalkSession({ walking: true, sceneRevision: revision }),
      { initialProps: { revision: "rev-002" }, wrapper: wrapper({ jobId: "job-1", enabled: true }) },
    );
    vi.advanceTimersByTime(6000);
    rerender({ revision: "rev-003" });
    vi.advanceTimersByTime(6000);
    unmount();

    expect(sent().map((item) => item.scene_revision)).toEqual(["rev-002", "rev-003"]);
    expect(sent()[1].started_at).toBe(sent()[0].ended_at);
  });
});
