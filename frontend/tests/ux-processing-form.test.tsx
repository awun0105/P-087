import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { restoreProcessing, useProcessingForm } from "@/features/studio/useProcessingForm";
import { evaluateProcessing, getProcessingOptions, suggestProcessingPreset } from "@/lib/api/studio";
import { ApiError } from "@/lib/api/client";
import type { ProcessingOptions } from "@/lib/contracts/studio";

vi.mock("@/lib/api/studio", () => ({ getProcessingOptions: vi.fn(), evaluateProcessing: vi.fn(), suggestProcessingPreset: vi.fn() }));
const evaluation: ProcessingOptions["default_evaluation"] = { blocking: false, resources: [], parameters: [], note: "fixture" };
const options: ProcessingOptions = {
  profile_id: "fixture",
  parameters: [{ key: "frames", group: "sampling", label: "Frames", description: "", kind: "integer", min: 1, max: 100, step: 1, unit: null, choices: null }],
  presets: { minimum_quality: { frames: 10 }, maximum: { frames: 100 }, machine_maximum: { frames: 100 } },
  capability: { worker_id: "fixture", measured_at: "2026-10-01", gpu_name: null, vram_total_gb: null, cpu_count: 8, ram_total_gb: 16, disk_free_gb: 20 },
  default_evaluation: evaluation, resource_note: "fixture only",
};
beforeEach(() => { vi.resetAllMocks(); vi.mocked(getProcessingOptions).mockResolvedValue({ ok: true, data: options }); vi.mocked(evaluateProcessing).mockResolvedValue({ ok: true, data: evaluation }); });
describe("thông số nháp và evaluation hiện hành", () => {
  it("manual edits cancel a pending suggestion so a late response cannot overwrite them", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof suggestProcessingPreset>>) => void;
    vi.mocked(suggestProcessingPreset).mockImplementation(() => new Promise((done) => { resolve = done; }));
    const hook = renderHook(() => useProcessingForm(true));
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 10 }));
    const preferences = { input_type: "video_continuous", environment: "indoor", subject_scope: "full_room", target_capacity: "balanced" } as const;
    let request!: Promise<void>;
    act(() => { request = hook.result.current.applyScenario(preferences); });
    expect(hook.result.current.suggesting).toBe(true);
    act(() => hook.result.current.setValue("frames", 27));
    await act(async () => { resolve({ ok: true, data: { preset_name: "video_indoor_walkthrough", params: { frames: 40 }, evaluation } }); await request; });
    expect(hook.result.current.values).toEqual({ frames: 27 });
    expect(hook.result.current.scenarioPreset).toBeNull();
  });
  it("applies a validated scenario and its evaluation together", async () => {
    vi.mocked(suggestProcessingPreset).mockResolvedValue({ ok: true, data: { preset_name: "video_single_object", params: { frames: 40 }, evaluation } });
    const hook = renderHook(() => useProcessingForm(true));
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 10 }));
    await act(async () => { await hook.result.current.applyScenario({ input_type: "video_loop_360", environment: "outdoor", subject_scope: "single_object", target_capacity: "balanced" }); });
    expect(hook.result.current.values).toEqual({ frames: 40 });
    expect(hook.result.current.scenarioPreset).toBe("video_single_object");
    expect(hook.result.current.evaluation).toEqual(evaluation);
  });
  it("chỉ phục hồi tham số còn trong schema và đúng range/type", () => {
    expect(restoreProcessing(options, { frames: 25, retired: 10 })).toEqual({ frames: 25 });
    for (const frames of [101, 1.5, "50"]) expect(restoreProcessing(options, { frames })).toEqual({ frames: 10 });
  });
  it("đợi draft rồi công bố đúng giá trị; không lộ preset mặc định để ghi đè draft", async () => {
    const seen: unknown[] = [];
    const hook = renderHook(({ ready }) => { const form = useProcessingForm(true, { frames: 25 }, ready); seen.push(form.values); return form; }, { initialProps: { ready: false } });
    await waitFor(() => expect(hook.result.current.options).not.toBeNull());
    expect(hook.result.current.values).toBeNull();
    hook.rerender({ ready: true });
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 25 }));
    expect(seen.filter(Boolean)).not.toContainEqual({ frames: 10 });
    await waitFor(() => expect(evaluateProcessing).toHaveBeenCalledWith({ frames: 25 }, expect.any(AbortSignal)));
  });
  it("evaluation cũ bị ẩn khi sửa; lỗi có thể thử lại mà không mất values", async () => {
    const hook = renderHook(() => useProcessingForm(true));
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 10 }));
    vi.mocked(evaluateProcessing).mockResolvedValueOnce({ ok: false, error: new ApiError(500, "private server details") });
    act(() => hook.result.current.setValue("frames", 30));
    expect(hook.result.current.evaluation).toBeNull();
    expect(hook.result.current.evaluating).toBe(true);
    await waitFor(() => expect(hook.result.current.error).not.toBeNull());
    act(() => hook.result.current.retry());
    await waitFor(() => expect(hook.result.current.evaluation).toEqual(evaluation));
    expect(hook.result.current.values).toEqual({ frames: 30 });
  });
});
