import { afterEach, describe, expect, it, vi } from "vitest";
import { suggestProcessingPreset } from "@/lib/api/studio";
import { parseSuggestResponse, type ParameterSpec, type ScenarioPreferences } from "@/lib/contracts/studio";

const preferences: ScenarioPreferences = {
  input_type: "video_loop_360", environment: "outdoor", subject_scope: "single_object", target_capacity: "standard",
  video: { duration_seconds: 180, display_width: 1920, display_height: 1080, frame_rate: 30 },
};
const params = { "colmap.matching_mode": "sequential_vocab_tree", "geometry.collision_mesh": "faces", "scene.max_objects": 1, "simulation.ground_plane": "disabled" };
const suggestion = {
  preset_name: "video_single_object", params,
  evaluation: {
    resources: ["vram", "ram", "disk"].map((resource) => ({ resource, required_gb: 1, available_gb: 32, status: "ok", message: "Đã đo" })),
    parameters: Object.keys(params).map((key) => ({ key, status: "ok", message: null })), blocking: false, note: "Ước lượng",
  },
  notes: ["Video 3 phút 0 giây: lấy 1,7 khung hình mỗi giây (tối đa 300 ảnh)"],
};

afterEach(() => vi.unstubAllGlobals());

describe("scenario processing contract", () => {
  it("accepts all downstream groups and validates a complete suggestion", () => {
    const groups: ParameterSpec["group"][] = ["sampling", "colmap", "brush", "geometry", "scene", "simulation"];
    expect(groups).toHaveLength(6);
    expect(parseSuggestResponse(suggestion)).toEqual(suggestion);
    // Server cũ chưa gửi ghi chú: coi như không có ghi chú.
    const older = Object.fromEntries(Object.entries(suggestion).filter(([key]) => key !== "notes"));
    expect(parseSuggestResponse(older).notes).toEqual([]);
  });

  it.each([
    { ...suggestion, preset_name: "" },
    { ...suggestion, params: { bad: true } },
    { ...suggestion, params: { bad: Infinity } },
    { ...suggestion, evaluation: null },
    { ...suggestion, evaluation: { ...suggestion.evaluation, resources: [] } },
    { ...suggestion, evaluation: { ...suggestion.evaluation, parameters: [{ key: "unknown", status: "ok", message: null }] } },
    { ...suggestion, notes: "một chuỗi" },
    { ...suggestion, notes: [1] },
  ])("rejects malformed recommendations before updating form values", (payload) => {
    expect(() => parseSuggestResponse(payload)).toThrow();
  });

  it("posts preferences to the actual backend route and parses the response", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(suggestion), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    expect(await suggestProcessingPreset(preferences, controller.signal)).toEqual({ ok: true, data: suggestion });
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/processing/suggest"), expect.objectContaining({
      method: "POST", body: JSON.stringify(preferences), signal: controller.signal,
    }));
  });

  it("returns a recoverable error for malformed successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
    const result = await suggestProcessingPreset(preferences);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.status).toBe(502);
  });

  it("preserves actionable backend rejection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Không đủ GPU" }), { status: 409 })));
    const result = await suggestProcessingPreset(preferences);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.detail).toBe("Không đủ GPU");
  });
});
