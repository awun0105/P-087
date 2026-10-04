/** Test điều hướng bằng fixture; canvas được thay bằng stub, không claim GPU proof. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { lazy, Suspense, type ComponentType } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScenePage } from "@/features/studio/ScenePage";
import { PageTitleProvider } from "@/features/shell/Breadcrumbs";
import { NextAction } from "@/features/studio/scene/NextAction";
import { getJob, getPreview, listJobAttempts } from "@/lib/api/endpoints";
import { getJobProgress, getJobScene, getSimulationPackage, getReviewState } from "@/lib/api/studio";
import { ApiError } from "@/lib/api/client";
import type { JobProgress } from "@/lib/contracts/studio";
import { parsePreview } from "@/lib/contracts/preview";
import { buildFixtureScene } from "./fixtures/scene";
import type { MetricDraft } from "@/features/studio/MetricConfirmView";

vi.mock("next/dynamic", () => ({ default: (loader: () => Promise<ComponentType>) => {
  const Component = lazy(async () => ({ default: await loader() }));
  return function StubDynamic(props: object) { return <Suspense fallback={<p>Đang tải tab…</p>}><Component {...props} /></Suspense>; };
} }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => ({ me: { auth_required: false, user: null } }) }));
vi.mock("@/features/studio/scene/ReviewTab", () => ({ ReviewTab: () => <p>Review stub</p> }));
vi.mock("@/features/studio/scene/ResultsTab", () => ({ ResultsTab: () => <p>Results stub</p> }));
vi.mock("@/features/studio/scene/StudioTab", () => ({ StudioTab: ({ mode, metricDraft, onMetricDraft, onMetricClose }: { mode: string; metricDraft?: MetricDraft; onMetricDraft: (draft: MetricDraft) => void; onMetricClose: () => void }) => <section aria-label="Canvas stub"><p>{mode}</p><p>{metricDraft?.typed.anchor || "Chưa nhập số đo"}</p><button onClick={() => onMetricDraft({ points: [[1, 2, 3]], typed: { anchor: "2.5", check: "1" } })}>Chọn điểm stub</button><button onClick={onMetricClose}>Về Tiến trình</button></section> }));
vi.mock("@/lib/api/endpoints", async (original) => ({ ...(await original<typeof import("@/lib/api/endpoints")>()), getJob: vi.fn(), getPreview: vi.fn(), listJobAttempts: vi.fn() }));
vi.mock("@/lib/api/studio", async (original) => ({ ...(await original<typeof import("@/lib/api/studio")>()), getJobProgress: vi.fn(), getJobScene: vi.fn(), getSimulationPackage: vi.fn(), getReviewState: vi.fn() }));
const progress: JobProgress = { job_id: "job-1", status: "RUNNING", current_stage: "ST-METRIC-CANONICALIZE", attempt: 1, started_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", completed_at: null, stages: [], preview_ready: true, waiting_for: "metric_confirmation", error: null };
beforeEach(() => {
  vi.resetAllMocks(); history.replaceState({}, "", "/scenes/job-1?tab=progress");
  vi.mocked(getJob).mockResolvedValue({ ok: false, error: new ApiError(404, "fixture metadata unavailable") });
  vi.mocked(getJobProgress).mockResolvedValue({ ok: true, data: progress });
  vi.mocked(listJobAttempts).mockResolvedValue({ ok: true, data: { job_id: "job-1", attempts: [] } });
  const ref = (type: string, path: string, stage = "ST-VISUAL-RECON") => ({ artifact_type: type, schema_version: "1.0", job_id: "job-1", producer_stage: stage, artifact_uri: "artifact://jobs/job-1/attempts/a1/" + path, artifact_checksum: "sha256:" + "a".repeat(64), data_class: "derived" });
  vi.mocked(getPreview).mockResolvedValue({ ok: true, data: parsePreview({ schema_version: "1.0", artifact_type: "ReconstructionPreview", job_id: "job-1", attempt_id: "a1", source_input_checksum: "sha256:" + "b".repeat(64), format: "gaussian_sog", producer: "brush", producer_version: "fixture", metric_status: "UNCONFIRMED", coordinate_frame: "sfm_world", unit: "arbitrary", delivery_ref: ref("GaussianSOG", "scene.sog"), source_visual_ref: ref("BrushVisualArtifact", "visual.json"), camera_pose_ref: ref("CameraPoseArtifact", "poses.json", "ST-CAMERA-POSE") }, "job-1") });
});
describe("workflow scene", () => {
  it("Progress không mount canvas; đóng metric thực sự về timeline, mở lại giữ draft", async () => {
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    await screen.findByRole("heading", { name: "Tiến trình xử lý" }, { timeout: 3000 });
    expect(screen.queryByRole("region", { name: "Canvas stub" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận tỉ lệ mét" }));
    await screen.findByText("Chưa nhập số đo");
    expect(location.search).toContain("tab=studio"); expect(location.search).toContain("mode=metric");
    fireEvent.click(screen.getByText("Chọn điểm stub"));
    expect(screen.getByText("2.5")).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByText("Về Tiến trình")); });
    expect(await screen.findByRole("heading", { name: "Tiến trình xử lý" })).toBeInTheDocument();
    expect(location.search).toContain("tab=progress");
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận tỉ lệ mét" }));
    await waitFor(() => expect(screen.getByText("2.5")).toBeVisible());
  });
  it("chỉ cho retry khi backend cho phép, không lặp CTA ở đúng panel", () => {
    const props = { jobId: "job-1", current: "progress" as const, mode: "scene" as const, sceneReady: false, revision: null, busy: false, onOpen: vi.fn(), onRetry: vi.fn() };
    const failed: JobProgress = { ...progress, status: "FAILED", waiting_for: null, error: { stage_id: "ST-VISUAL-RECON", error_code: "fixture", human_message: "fixture", retryable: false } };
    const view = render(<NextAction {...props} progress={failed} />);
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
    view.rerender(<NextAction {...props} progress={{ ...failed, error: { ...failed.error!, retryable: true } }} />);
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" })); expect(props.onRetry).toHaveBeenCalledOnce();
    view.rerender(<NextAction {...props} progress={progress} current="studio" mode="metric" />);
    expect(screen.queryByRole("button", { name: "Xác nhận tỉ lệ mét" })).toBeNull();
  });
  it("lỗi đọc gói không bị diễn giải thành sẵn sàng tạo gói", async () => {
    const response = buildFixtureScene();
    const scene = response.scene;
    vi.mocked(getJobScene).mockResolvedValue({ ok: true, data: response });
    vi.mocked(getSimulationPackage).mockRejectedValue(new ApiError(500, "private diagnostic"));
    vi.mocked(getReviewState).mockRejectedValue(new ApiError(404, "No review"));
    render(<NextAction jobId="job-1" progress={{ ...progress, status: "SUCCEEDED", waiting_for: null }} current="progress" mode="scene" sceneReady revision={scene.scene_revision} busy={false} onOpen={vi.fn()} onRetry={vi.fn()} />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mở tạo gói mô phỏng" })).toBeNull();
    expect(screen.queryByText("private diagnostic")).toBeNull();
  });
  it("pipeline v2: ứng viên (active=false) vẫn tính là chờ xác nhận; tách vật lỗi thì dẫn về Studio để chọn", async () => {
    const response = buildFixtureScene();
    const candidate = { ...response.scene.objects[0], state: "CANDIDATE" as const, active: false };
    const scene = { ...response.scene, objects: [candidate] };
    vi.mocked(getJobScene).mockResolvedValue({ ok: true, data: { ...response, scene } });
    vi.mocked(getSimulationPackage).mockRejectedValue(new ApiError(404, "none"));
    vi.mocked(getReviewState).mockRejectedValue(new ApiError(404, "none"));
    const done = { ...progress, status: "SUCCEEDED" as const, waiting_for: null };
    const view = render(<NextAction jobId="job-1" progress={done} current="progress" mode="scene" sceneReady revision={scene.scene_revision} busy={false} onOpen={vi.fn()} onRetry={vi.fn()} />);
    expect(await screen.findByText("Cần xác nhận vật thể")).toBeInTheDocument();
    expect(screen.getByText("1 ứng viên chưa được xác nhận.")).toBeInTheDocument();
    view.unmount();

    const failed = { ...scene, objects: [], provenance: { ...scene.provenance, object_extraction: "objectify_failed_awaiting_choice" } };
    vi.mocked(getJobScene).mockResolvedValue({ ok: true, data: { ...response, scene: failed } });
    render(<NextAction jobId="job-1" progress={done} current="progress" mode="scene" sceneReady revision={scene.scene_revision} busy={false} onOpen={vi.fn()} onRetry={vi.fn()} />);
    expect(await screen.findByText("Tách theo vật chưa thành công")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mở Studio để chọn" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mở tạo gói mô phỏng" })).toBeNull();
  });
});
