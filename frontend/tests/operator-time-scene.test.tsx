/** Trang scene gắn bộ đếm phút công người theo tab: đổi tab gửi lô của tab cũ; người xem không sửa được thì không gửi. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { lazy, Suspense, type ComponentType } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScenePage } from "@/features/studio/ScenePage";
import { PageTitleProvider } from "@/features/shell/Breadcrumbs";
import { getJob, getPreview, listJobAttempts } from "@/lib/api/endpoints";
import { getJobProgress, getJobScene, getSimulationPackage, getReviewState, retryJob } from "@/lib/api/studio";
import { postOperatorTime } from "@/lib/api/value";
import { ApiError } from "@/lib/api/client";
import type { Me } from "@/lib/api/auth";
import type { JobProgress } from "@/lib/contracts/studio";
import { parsePreview } from "@/lib/contracts/preview";

vi.mock("next/dynamic", () => ({ default: (loader: () => Promise<ComponentType>) => {
  const Component = lazy(async () => ({ default: await loader() }));
  return function StubDynamic(props: object) { return <Suspense fallback={<p>Đang tải tab…</p>}><Component {...props} /></Suspense>; };
} }));
const authState = vi.hoisted(() => ({ me: { auth_required: false, user: null } as Me, refresh: vi.fn() }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => authState }));
vi.mock("@/features/studio/scene/ReviewTab", () => ({ ReviewTab: () => <p>Review stub</p> }));
vi.mock("@/features/studio/scene/ResultsTab", () => ({ ResultsTab: () => <p>Results stub</p> }));
vi.mock("@/features/studio/scene/StudioTab", () => ({ StudioTab: () => <section aria-label="Canvas stub"><p>Studio stub</p></section> }));
vi.mock("@/lib/api/endpoints", async (original) => ({ ...(await original<typeof import("@/lib/api/endpoints")>()), getJob: vi.fn(), getPreview: vi.fn(), listJobAttempts: vi.fn() }));
vi.mock("@/lib/api/studio", async (original) => ({ ...(await original<typeof import("@/lib/api/studio")>()), getJobProgress: vi.fn(), getJobScene: vi.fn(), getSimulationPackage: vi.fn(), getReviewState: vi.fn(), retryJob: vi.fn() }));
vi.mock("@/lib/api/value", () => ({ postOperatorTime: vi.fn(async () => undefined), postWalkSession: vi.fn(async () => undefined) }));

const ref = (type: string, path: string, stage = "ST-VISUAL-RECON") => ({ artifact_type: type, schema_version: "1.0", job_id: "job-1", producer_stage: stage, artifact_uri: "artifact://jobs/job-1/attempts/a1/" + path, artifact_checksum: "sha256:" + "a".repeat(64), data_class: "derived" });
const progress: JobProgress = { job_id: "job-1", status: "SUCCEEDED", current_stage: "ST-METRIC-CANONICALIZE", attempt: 1, started_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", completed_at: "2026-10-01T01:00:00Z", stages: [], preview_ready: true, waiting_for: null, error: null, capabilities: { can_mutate: true, can_cancel: false, can_retry: false } };

function postedSurfaces(): string[] {
  return vi.mocked(postOperatorTime).mock.calls.map((call) => call[1].surface);
}

/** Một nhịp đồng hồ thật (đồng hồ của hook đếm mỗi giây). */
const oneTick = () => new Promise((resolve) => setTimeout(resolve, 1200));

beforeEach(() => {
  vi.resetAllMocks();
  history.replaceState({}, "", "/scenes/job-1?tab=progress");
  authState.me = { auth_required: false, user: null };
  authState.refresh.mockResolvedValue(undefined);
  vi.mocked(getJob).mockResolvedValue({ ok: false, error: new ApiError(404, "fixture metadata unavailable") });
  vi.mocked(getJobProgress).mockResolvedValue({ ok: true, data: progress });
  vi.mocked(retryJob).mockResolvedValue({ job_id: "job-1", status: "QUEUED", job_manifest_checksum: "sha256:" + "c".repeat(64) });
  vi.mocked(listJobAttempts).mockResolvedValue({ ok: true, data: { job_id: "job-1", attempts: [] } });
  vi.mocked(getPreview).mockResolvedValue({ ok: true, data: parsePreview({ schema_version: "1.0", artifact_type: "ReconstructionPreview", job_id: "job-1", attempt_id: "a1", source_input_checksum: "sha256:" + "b".repeat(64), format: "gaussian_sog", producer: "brush", producer_version: "fixture", metric_status: "UNCONFIRMED", coordinate_frame: "sfm_world", unit: "arbitrary", delivery_ref: ref("GaussianSOG", "scene.sog"), source_visual_ref: ref("BrushVisualArtifact", "visual.json"), camera_pose_ref: ref("CameraPoseArtifact", "poses.json", "ST-CAMERA-POSE") }, "job-1") });
  vi.mocked(getJobScene).mockResolvedValue({ ok: false, error: new ApiError(404, "no scene") });
  vi.mocked(getSimulationPackage).mockRejectedValue(new ApiError(404, "no package"));
  vi.mocked(getReviewState).mockRejectedValue(new ApiError(404, "no review"));
});

describe("operator time on the scene page", () => {
  it("sends the old tab's batch when the user switches to Studio", async () => {
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    await screen.findByRole("heading", { name: "Tiến trình xử lý" });

    fireEvent.keyDown(window, { key: "a" });
    await oneTick();
    fireEvent.click(await screen.findByRole("tab", { name: "Studio" }));
    await screen.findByRole("region", { name: "Canvas stub" });

    await waitFor(() => expect(postedSurfaces()).toContain("progress"));
    const first = vi.mocked(postOperatorTime).mock.calls.find((call) => call[1].surface === "progress")?.[1];
    expect(first?.active_seconds).toBeGreaterThan(0);
  });

  it("sends nothing for a viewer who cannot mutate the job", async () => {
    vi.mocked(getJobProgress).mockResolvedValue({ ok: true, data: { ...progress, capabilities: { can_mutate: false, can_cancel: false, can_retry: false } } });
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    await screen.findByRole("heading", { name: "Tiến trình xử lý" });

    fireEvent.keyDown(window, { key: "a" });
    await oneTick();
    fireEvent.click(await screen.findByRole("tab", { name: "Studio" }));
    await screen.findByRole("region", { name: "Canvas stub" });

    expect(postOperatorTime).not.toHaveBeenCalled();
  });
});
