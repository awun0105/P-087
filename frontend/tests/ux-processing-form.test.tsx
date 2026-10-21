import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { restoreProcessing, useProcessingForm, videoFactsFromObserved } from "@/features/studio/useProcessingForm";
import { evaluateProcessing, getProcessingOptions, suggestProcessingPreset } from "@/lib/api/studio";
import { ApiError } from "@/lib/api/client";
import type { ProcessingOptions } from "@/lib/contracts/studio";
import type { VideoStreamMetadata } from "@/lib/contracts/videoPreparation";

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
  it("debounces edits for 300 ms after the last change and aborts an older evaluation", async () => {
    vi.useFakeTimers();
    const hook = renderHook(() => useProcessingForm(true));
    try {
      await act(async () => { await Promise.resolve(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(hook.result.current.values).toEqual({ frames: 10 });
      vi.mocked(evaluateProcessing).mockClear();
      act(() => hook.result.current.setValue("frames", 20));
      await act(async () => { await vi.advanceTimersByTimeAsync(200); });
      expect(evaluateProcessing).not.toHaveBeenCalled();
      act(() => hook.result.current.setValue("frames", 30));
      await act(async () => { await vi.advanceTimersByTimeAsync(299); });
      expect(evaluateProcessing).not.toHaveBeenCalled();
      await act(async () => { await vi.advanceTimersByTimeAsync(1); });
      expect(evaluateProcessing).toHaveBeenCalledTimes(1);
      expect(evaluateProcessing).toHaveBeenLastCalledWith({ frames: 30 }, expect.any(AbortSignal));
      const signal = vi.mocked(evaluateProcessing).mock.calls[0][1]!;
      act(() => hook.result.current.setValue("frames", 40));
      expect(signal.aborted).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(300); });
      expect(evaluateProcessing).toHaveBeenCalledTimes(2);
      expect(evaluateProcessing).toHaveBeenLastCalledWith({ frames: 40 }, expect.any(AbortSignal));
    } finally {
      hook.unmount();
      vi.useRealTimers();
    }
  });
  it("manual edits cancel a pending suggestion so a late response cannot overwrite them", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof suggestProcessingPreset>>) => void;
    vi.mocked(suggestProcessingPreset).mockImplementation(() => new Promise((done) => { resolve = done; }));
    const hook = renderHook(() => useProcessingForm(true));
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 10 }));
    const preferences = { input_type: "video_continuous", environment: "indoor", subject_scope: "full_room", target_capacity: "standard" } as const;
    let request!: Promise<void>;
    act(() => { request = hook.result.current.applyScenario(preferences); });
    expect(hook.result.current.suggesting).toBe(true);
    act(() => hook.result.current.setValue("frames", 27));
    await act(async () => { resolve({ ok: true, data: { preset_name: "video_indoor_walkthrough", params: { frames: 40 }, evaluation, notes: [] } }); await request; });
    expect(hook.result.current.values).toEqual({ frames: 27 });
    expect(hook.result.current.scenarioPreset).toBeNull();
  });
  it("applies a validated scenario and its evaluation together", async () => {
    vi.mocked(suggestProcessingPreset).mockResolvedValue({ ok: true, data: { preset_name: "video_single_object", params: { frames: 40 }, evaluation, notes: [] } });
    const hook = renderHook(() => useProcessingForm(true));
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 10 }));
    await act(async () => { await hook.result.current.applyScenario({ input_type: "video_loop_360", environment: "outdoor", subject_scope: "single_object", target_capacity: "standard" }); });
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

const reviewOptions: ProcessingOptions = {
  ...options,
  parameters: [
    ...options.parameters,
    { key: "scene.geometry_review", group: "scene", label: "Duyệt tách vật", description: "", kind: "choice", min: null, max: null, step: null, unit: null, choices: [{ value: "required", label: "Dừng" }, { value: "auto", label: "Tạo mesh ngay" }] },
  ],
  presets: {
    minimum_quality: { frames: 10, "scene.geometry_review": "required" },
    maximum: { frames: 100, "scene.geometry_review": "required" },
    machine_maximum: { frames: 100, "scene.geometry_review": "required" },
  },
};

describe("lựa chọn duyệt tách vật trong hook", () => {
  it("giữ đánh dấu preset khi đổi lựa chọn duyệt, và giữ lựa chọn đó khi đổi preset", async () => {
    vi.mocked(getProcessingOptions).mockResolvedValue({ ok: true, data: reviewOptions });
    const hook = renderHook(() => useProcessingForm(true));
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 10, "scene.geometry_review": "required" }));
    expect(hook.result.current.activePreset).toBe("minimum_quality");
    act(() => hook.result.current.setValue("scene.geometry_review", "auto"));
    expect(hook.result.current.activePreset).toBe("minimum_quality");
    act(() => hook.result.current.applyPreset("machine_maximum"));
    expect(hook.result.current.values).toEqual({ frames: 100, "scene.geometry_review": "auto" });
    expect(hook.result.current.activePreset).toBe("machine_maximum");
    act(() => hook.result.current.setValue("frames", 50));
    expect(hook.result.current.activePreset).toBeNull();
  });

  it("kịch bản không ghi đè lựa chọn duyệt tách vật người dùng đã chọn", async () => {
    vi.mocked(getProcessingOptions).mockResolvedValue({ ok: true, data: reviewOptions });
    vi.mocked(suggestProcessingPreset).mockResolvedValue({ ok: true, data: { preset_name: "video_single_object", params: { frames: 40, "scene.geometry_review": "required" }, evaluation, notes: [] } });
    const hook = renderHook(() => useProcessingForm(true));
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 10, "scene.geometry_review": "required" }));
    act(() => hook.result.current.setValue("scene.geometry_review", "auto"));
    await act(async () => { await hook.result.current.applyScenario({ input_type: "video_loop_360", environment: "outdoor", subject_scope: "single_object", target_capacity: "standard" }); });
    expect(hook.result.current.values).toEqual({ frames: 40, "scene.geometry_review": "auto" });
    expect(hook.result.current.scenarioPreset).toBe("video_single_object");
    expect(hook.result.current.evaluation).toEqual(evaluation);
  });
});

const facts = { duration_seconds: 180, display_width: 1920, display_height: 1080, frame_rate: 30 };

describe("tự gợi ý khi mở bước cấu hình (T-071 D1)", () => {
  it("gợi ý ngay theo video thật với kịch bản mặc định, không gọi ước lượng thừa", async () => {
    vi.mocked(suggestProcessingPreset).mockResolvedValue({ ok: true, data: { preset_name: "video_indoor_walkthrough", params: { frames: 60 }, evaluation, notes: ["Video 3 phút 0 giây: lấy 1,7 khung hình mỗi giây (tối đa 300 ảnh)"] } });
    const hook = renderHook(({ open }) => useProcessingForm(true, null, true, { video: facts, suggest: open }), { initialProps: { open: false } });
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 10 }));
    expect(suggestProcessingPreset).not.toHaveBeenCalled();
    hook.rerender({ open: true });
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 60 }));
    expect(suggestProcessingPreset).toHaveBeenCalledTimes(1);
    expect(suggestProcessingPreset).toHaveBeenCalledWith({ input_type: "video_continuous", environment: "indoor", subject_scope: "full_room", target_capacity: "standard", video: facts }, expect.any(AbortSignal));
    expect(hook.result.current.scenarioPreferences?.target_capacity).toBe("standard");
    expect(hook.result.current.scenarioNotes).toEqual(["Video 3 phút 0 giây: lấy 1,7 khung hình mỗi giây (tối đa 300 ảnh)"]);
    expect(hook.result.current.evaluation).toEqual(evaluation);
    await new Promise((done) => setTimeout(done, 400));
    expect(evaluateProcessing).not.toHaveBeenCalled();
    hook.rerender({ open: true });
    expect(suggestProcessingPreset).toHaveBeenCalledTimes(1);
    act(() => hook.result.current.setValue("frames", 33));
    expect(hook.result.current.scenarioNotes).toEqual([]);
  });

  it("giữ draft khôi phục nhưng vẫn gửi video khi đổi kịch bản; bộ ảnh không gửi video", async () => {
    vi.mocked(suggestProcessingPreset).mockResolvedValue({ ok: true, data: { preset_name: "video_single_object", params: { frames: 40 }, evaluation, notes: [] } });
    const hook = renderHook(() => useProcessingForm(true, { frames: 25 }, true, { video: facts, suggest: true }));
    await waitFor(() => expect(hook.result.current.values).toEqual({ frames: 25 }));
    await new Promise((done) => setTimeout(done, 50));
    expect(suggestProcessingPreset).not.toHaveBeenCalled();
    await act(async () => { await hook.result.current.applyScenario({ input_type: "video_loop_360", environment: "indoor", subject_scope: "single_object", target_capacity: "high_quality" }); });
    expect(suggestProcessingPreset).toHaveBeenLastCalledWith(expect.objectContaining({ target_capacity: "high_quality", video: facts }), expect.any(AbortSignal));
    await act(async () => { await hook.result.current.applyScenario({ input_type: "photo_set", environment: "indoor", subject_scope: "full_room", target_capacity: "standard" }); });
    expect(suggestProcessingPreset).toHaveBeenLastCalledWith(expect.objectContaining({ input_type: "photo_set", video: null, photo_count: null }), expect.any(AbortSignal));
  });

  it("đổi thời lượng/độ phân giải từ observed_video, bỏ số không hợp lệ", () => {
    const observed = { display_width: 1080, display_height: 1920, duration_ticks: 2_700_000, time_base: { numerator: 1, denominator: 90_000 }, frame_rate: { numerator: 30000, denominator: 1001 } } as VideoStreamMetadata;
    expect(videoFactsFromObserved(observed)).toEqual({ duration_seconds: 30, display_width: 1080, display_height: 1920, frame_rate: 30000 / 1001 });
    expect(videoFactsFromObserved({ ...observed, frame_rate: null })?.frame_rate).toBeNull();
    expect(videoFactsFromObserved({ ...observed, duration_ticks: 0 })).toBeNull();
    expect(videoFactsFromObserved({ ...observed, display_width: 8 })).toBeNull();
    expect(videoFactsFromObserved(null)).toBeNull();
  });
});
