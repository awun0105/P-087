import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePolling } from "@/features/studio/usePolling";

afterEach(() => vi.useRealTimers());

describe("usePolling interval changes (T-061)", () => {
  it("does not fire an extra immediate request when only the interval changes", async () => {
    vi.useFakeTimers();
    const task = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(({ ms }) => usePolling(task, ms, true), { initialProps: { ms: 3000 } });
    await vi.advanceTimersByTimeAsync(0);
    expect(task).toHaveBeenCalledTimes(1);
    rerender({ ms: 15000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(15000);
    expect(task).toHaveBeenCalledTimes(2);
  });
});
