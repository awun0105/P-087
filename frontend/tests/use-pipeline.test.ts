import { afterEach, describe, expect, it, vi } from "vitest";

import { pipelinePollInterval } from "@/features/studio/scene/pipeline";
import { getJobPipeline } from "@/lib/api/studio";
import type { PipelineView } from "@/lib/contracts/pipeline";

const progress = {
  job_id: "job-1", status: "RUNNING", current_stage: "ST-CAMERA-POSE", attempt: 1,
  started_at: "2026-10-20T08:00:00Z", updated_at: "2026-10-20T08:00:00Z", completed_at: null,
  stages: [], preview_ready: false, waiting_for: null, error: null,
};

function view(kind: PipelineView["next_action"]["kind"], owner: "system" | "user", states: string[] = []): PipelineView {
  return {
    job_id: "job-1", scene_revision: null, usable: false, current_step: null, wait: null, version: "v1",
    next_action: { kind, step_id: null, owner, pending_count: null },
    steps: states.map((state) => ({ step_id: "ST-CAMERA-POSE", actor: "system", state, started_at: null, completed_at: null, timing_source: "none", phase: null, error: null, note: null })) as PipelineView["steps"],
    progress: progress as PipelineView["progress"], objectify: null, gpu: null,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("pipeline poll interval (T-060)", () => {
  it("polls every 3 s while the system works", () => {
    expect(pipelinePollInterval(view("wait_system", "system"))).toBe(3000);
    expect(pipelinePollInterval(view("scene_ready", "user", ["running"]))).toBe(3000);
  });
  it("polls every 15 s while waiting for the user so another tab's confirmation shows up", () => {
    expect(pipelinePollInterval(view("confirm_metric", "user"))).toBe(15000);
    expect(pipelinePollInterval(view("review_objects", "user"))).toBe(15000);
  });
  it("polls every 60 s once nothing is pending", () => {
    expect(pipelinePollInterval(view("released", "user"))).toBe(60000);
    expect(pipelinePollInterval(view("create_package", "user"))).toBe(60000);
  });
  it("polls fast before the first answer", () => {
    expect(pipelinePollInterval(null)).toBe(3000);
  });
});

describe("getJobPipeline (T-060)", () => {
  it("sends If-None-Match and reports 304 as not modified", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 304 }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await getJobPipeline("job-1", '"v1"');
    expect(result).toEqual({ ok: true, data: { notModified: true } });
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).toMatchObject({ "If-None-Match": '"v1"' });
  });
  it("returns the view and its ETag", async () => {
    const body = view("wait_system", "system");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200, headers: { ETag: '"v2"' } })));
    const result = await getJobPipeline("job-1", null);
    expect(result.ok && !result.data.notModified && result.data.etag).toBe('"v2"');
    expect(result.ok && !result.data.notModified && result.data.view.next_action.kind).toBe("wait_system");
  });
});

describe("timeline rows from backend steps (T-061)", () => {
  it("keeps the backend order, adds no fake rows and shows durations for system steps only", async () => {
    const { timelineFromSteps } = await import("@/features/studio/scene/pipeline");
    const base = view("review_objects", "user");
    const steps = [
      { step_id: "ST-OBJECT-EXTRACT", actor: "system", state: "succeeded", started_at: "2026-10-20T08:00:00Z", completed_at: "2026-10-20T08:02:00Z", timing_source: "recorded", phase: null, error: null, note: null },
      { step_id: "ST-OBJECT-CONFIRM", actor: "user", state: "waiting", started_at: "2026-10-20T08:02:00Z", completed_at: null, timing_source: "inferred", phase: null, error: null, note: null },
      { step_id: "ST-SCENE-DECOMPOSE", actor: "system", state: "queued", started_at: null, completed_at: null, timing_source: "none", phase: null, error: null, note: null },
    ] as PipelineView["steps"];
    const { stages, stageList } = timelineFromSteps({ ...base, steps }, Date.parse("2026-10-20T08:12:00Z"));
    expect(stageList.map((meta) => meta.id)).toEqual(["ST-OBJECT-EXTRACT", "ST-OBJECT-CONFIRM", "ST-SCENE-DECOMPOSE"]);
    expect(stages[0].seconds).toBe(120);
    expect(stages[1].seconds).toBeNull();
    expect(stages[1].note).toContain("Chờ bạn 10 phút");
    expect(stages[2].state).toBe("pending");
    expect(stages[2].note).toContain("Đang chờ máy xử lý");
  });

  it("names the LOD step and shows how long it has run (T-070)", async () => {
    const { timelineFromSteps } = await import("@/features/studio/scene/pipeline");
    const { STAGE_IDS } = await import("@/lib/contracts/api");
    expect(STAGE_IDS).toContain("ST-VIEW-LOD");
    const base = view("review_objects", "user");
    const steps = [
      { step_id: "ST-VIEW-LOD", actor: "system", state: "running", started_at: "2026-10-20T08:10:00Z", completed_at: null, timing_source: "recorded", phase: null, error: null, note: null },
    ] as PipelineView["steps"];
    const { stages, stageList } = timelineFromSteps({ ...base, steps }, Date.parse("2026-10-20T08:12:00Z"));
    expect(stageList[0].title).toBe("Chuẩn bị xem 3D mượt");
    expect(stages[0].seconds).toBe(120);
  });
});
