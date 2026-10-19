/** Chuông thông báo trên Draft (T-021): không bao giờ gợi ý tạo gói, và nêu việc dựng đang chạy hoặc lỗi Tạo mesh. */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NextAction } from "@/features/studio/scene/NextAction";
import { getJobScene, getObjectifyState, getReviewState, getSimulationPackage, type ObjectifyState } from "@/lib/api/studio";
import { ApiError } from "@/lib/api/client";
import type { SceneIR } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";
import { buildFixtureScene } from "./fixtures/scene";

vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => ({ me: { auth_required: false, user: null }, refresh: vi.fn() }) }));
vi.mock("@/lib/api/studio", async (original) => ({
  ...(await original<typeof import("@/lib/api/studio")>()),
  getJobScene: vi.fn(),
  getSimulationPackage: vi.fn(),
  getReviewState: vi.fn(),
  getObjectifyState: vi.fn(),
}));

const done: JobProgress = {
  job_id: "job-1", status: "SUCCEEDED", current_stage: "ST-OBJECT-EXTRACT", attempt: 1,
  started_at: "2026-10-10T00:00:00Z", updated_at: "2026-10-10T01:00:00Z", completed_at: "2026-10-10T01:00:00Z",
  stages: [], preview_ready: true, error: null, waiting_for: null,
  capabilities: { can_mutate: true, can_cancel: false, can_retry: false },
};

function objectify(overrides: Partial<ObjectifyState> = {}): ObjectifyState {
  return {
    status: "idle", mode: null, scene_revision: "rev-001", awaiting_choice: false, object_centric: true, available: true, note: null,
    base_revision: null, result_revision: null, error: null, resource_wait: null, cancellation_requested: false,
    object_geometry: "awaiting_review", ...overrides,
  };
}

/** Scene theo fixture với khoá object_geometry và số ứng viên tuỳ chọn. */
function sceneWith(geometry: "awaiting_review" | "ready", candidates: number): SceneIR {
  const base = buildFixtureScene().scene;
  const template = base.objects[0];
  const objects = Array.from({ length: candidates }, (_, index) => ({
    ...template,
    id: `candidate-${index + 1}`,
    name: `Ứng viên ${index + 1}`,
    state: "CANDIDATE" as const,
    active: false,
    provenance: { ...template.provenance, review: undefined },
  }));
  return { ...base, objects, provenance: { ...base.provenance, object_geometry: geometry } } as unknown as SceneIR;
}

function renderBell(scene: SceneIR, onOpen = vi.fn(), current: "progress" | "studio" = "progress") {
  vi.mocked(getJobScene).mockResolvedValue({ ok: true, data: { ...buildFixtureScene(), scene } } as never);
  vi.mocked(getSimulationPackage).mockRejectedValue(new ApiError(404, "none"));
  vi.mocked(getReviewState).mockRejectedValue(new ApiError(404, "none"));
  return render(
    <NextAction
      jobId="job-1"
      progress={done}
      current={current}
      mode="scene"
      sceneReady
      revision={scene.scene_revision}
      busy={false}
      onOpen={onOpen}
      onRetry={vi.fn()}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("chuông trên Draft", () => {
  it("Draft có ba ứng viên: nêu số vật chờ và dẫn đến Studio, không gợi ý tạo gói", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify());
    const onOpen = vi.fn();
    renderBell(sceneWith("awaiting_review", 3), onOpen);

    expect(await screen.findByText("Duyệt vật rồi Tạo mesh")).toBeInTheDocument();
    expect(screen.getByText("3 vật chờ xác nhận. Chỉnh vùng nếu cần, rồi bấm Tạo mesh trong Studio.")).toBeInTheDocument();
    expect(screen.queryByText("Sẵn sàng tạo gói")).toBeNull();
    expect(screen.queryByRole("button", { name: "Mở tạo gói mô phỏng" })).toBeNull();
    screen.getByRole("button", { name: "Mở để duyệt" }).click();
    expect(onOpen).toHaveBeenCalledWith("studio", "scene");
  });

  it("Draft không có ứng viên: vẫn chỉ hướng dẫn tạo mesh, không nói số vật", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify());
    renderBell(sceneWith("awaiting_review", 0));

    expect(await screen.findByText("Duyệt vật rồi Tạo mesh")).toBeInTheDocument();
    expect(screen.getByText("Chỉnh vùng nếu cần, rồi bấm Tạo mesh trong Studio.")).toBeInTheDocument();
    expect(screen.queryByText("Sẵn sàng tạo gói")).toBeNull();
  });

  it("đang tạo mesh: nêu tên việc và phase, nút xem tiến trình", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "running", mode: "geometry", phase: "shell", operation_id: "op-1" }));
    const onOpen = vi.fn();
    renderBell(sceneWith("awaiting_review", 2), onOpen, "studio");

    expect(await screen.findByText("Đang tạo mesh")).toBeInTheDocument();
    expect(screen.getByText("Dựng vỏ vật")).toBeInTheDocument();
    screen.getByRole("button", { name: "Xem tiến trình" }).click();
    expect(onOpen).toHaveBeenCalledWith("progress", undefined);
  });

  it("Tạo mesh lỗi cùng revision: nêu lý do và dẫn đến Studio để sửa vùng", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ status: "failed", mode: "geometry", base_revision: "rev-001", error: "Vỏ của Ghế không dựng được" }));
    const onOpen = vi.fn();
    renderBell(sceneWith("awaiting_review", 2), onOpen);

    expect(await screen.findByText("Tạo mesh chưa xong")).toBeInTheDocument();
    expect(screen.getByText("Vỏ của Ghế không dựng được")).toBeInTheDocument();
    screen.getByRole("button", { name: "Mở để sửa vùng" }).click();
    expect(onOpen).toHaveBeenCalledWith("studio", "scene");
  });

  it("Ready không có ứng viên: vẫn là luồng cũ, gợi ý tạo gói", async () => {
    vi.mocked(getObjectifyState).mockResolvedValue(objectify({ object_geometry: "ready", status: "done" }));
    renderBell(sceneWith("ready", 0));

    expect(await screen.findByText("Sẵn sàng tạo gói")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mở tạo gói mô phỏng" })).toBeInTheDocument();
  });
});
