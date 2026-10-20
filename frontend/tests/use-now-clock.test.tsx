import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useNow } from "@/features/studio/scene/state";

afterEach(() => vi.useRealTimers());

describe("shared clock (T-060)", () => {
  it("ticks every 5 s while active, not every second", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useNow(true));
    const first = result.current;
    act(() => { vi.advanceTimersByTime(4000); });
    expect(result.current).toBe(first);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(result.current).toBeGreaterThan(first);
  });
  it("does not tick while inactive", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useNow(false));
    const first = result.current;
    act(() => { vi.advanceTimersByTime(20000); });
    expect(result.current).toBe(first);
  });
});
