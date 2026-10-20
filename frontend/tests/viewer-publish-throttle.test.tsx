/** T-064: thời gian quỹ đạo và tiến độ tải báo cho giao diện tối đa 4 lần/giây; trạng thái khác báo ngay. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createRuntimePublisher } from "@/features/viewer/runtime-publisher";
import type { PlayCanvasRuntime } from "@/features/viewer/PlayCanvasScene";

const base: PlayCanvasRuntime = {
  loaded: true, progress: 100, hasCollision: false, walkAllowed: false, cameraMode: "orbit", hasAnimation: true,
  animationPaused: false, animationDuration: 10, animationTime: 0, graphicsBackend: undefined,
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("runtime publisher (T-064)", () => {
  it("emits at most 5 times for 60 animation ticks in one second and ends on the last value", () => {
    const emit = vi.fn();
    const publish = createRuntimePublisher(emit);
    for (let index = 1; index <= 60; index += 1) {
      publish({ ...base, animationTime: index / 60 });
      vi.advanceTimersByTime(1000 / 60);
    }
    vi.advanceTimersByTime(300);
    expect(emit.mock.calls.length).toBeLessThanOrEqual(5);
    expect(emit.mock.calls.at(-1)![0].animationTime).toBe(1);
  });

  it("emits other state changes immediately", () => {
    const emit = vi.fn();
    const publish = createRuntimePublisher(emit);
    publish(base);
    publish({ ...base, animationTime: 0.1 });
    publish({ ...base, animationTime: 0.2, cameraMode: "walk" });
    expect(emit).toHaveBeenCalledTimes(2);
    expect(emit.mock.calls[1][0]).toMatchObject({ cameraMode: "walk", animationTime: 0.2 });
  });

  it("drops a pending tick after dispose", () => {
    const emit = vi.fn();
    const publish = createRuntimePublisher(emit);
    publish(base);
    publish({ ...base, progress: 50 });
    publish.dispose();
    vi.advanceTimersByTime(1000);
    expect(emit).toHaveBeenCalledTimes(1);
  });
});
