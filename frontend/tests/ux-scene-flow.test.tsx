/** Test điều hướng bằng fixture; canvas được thay bằng stub, không claim GPU proof. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { lazy, Suspense, type ComponentType } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScenePage } from "@/features/studio/ScenePage";
import { PageTitleProvider } from "@/features/shell/Breadcrumbs";
import { NextAction } from "@/features/studio/scene/NextAction";
import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import { getJob, getPreview, listJobAttempts } from "@/lib/api/endpoints";
import { getJobPipeline, getJobScene, getSimulationPackage, getReviewState, retryJob } from "@/lib/api/studio";
import { ApiError } from "@/lib/api/client";
import type { Me } from "@/lib/api/auth";
import type { JobProgress } from "@/lib/contracts/studio";
import { parsePreview } from "@/lib/contracts/preview";
import { buildFixtureScene } from "./fixtures/scene";
import type { MetricDraft } from "@/features/studio/MetricConfirmView";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

vi.mock("next/dynamic", () => ({ default: (loader: () => Promise<ComponentType>) => {
  const Component = lazy(async () => ({ default: await loader() }));
  return function StubDynamic(props: object) { return <Suspense fallback={<p>Đang tải tab…</p>}><Component {...props} /></Suspense>; };
} }));
const authState = vi.hoisted(() => ({ me: { auth_required: false, user: null } as Me, refresh: vi.fn() }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => authState }));
vi.mock("@/features/studio/scene/ReviewTab", () => ({ ReviewTab: () => <p>Review stub</p> }));
vi.mock("@/features/studio/scene/ResultsTab", () => ({ ResultsTab: () => <p>Results stub</p> }));
vi.mock("@/features/studio/scene/StudioTab", () => ({ StudioTab: ({ mode, canMutate, metricDraft, onMetricDraft, onMetricClose }: { mode: string; canMutate: boolean; metricDraft?: MetricDraft; onMetricDraft: (draft: MetricDraft) => void; onMetricClose: () => void }) => <section aria-label="Canvas stub"><p>{mode}</p>{!canMutate && <p>Quyền chỉ xem</p>}<p>{metricDraft?.typed.anchor || "Chưa nhập số đo"}</p>{canMutate && <button onClick={() => onMetricDraft({ points: [[1, 2, 3]], typed: { anchor: "2.5", check: "1" } })}>Chọn điểm stub</button>}<button onClick={onMetricClose}>Về Tiến trình</button></section> }));
vi.mock("@/lib/api/endpoints", async (original) => ({ ...(await original<typeof import("@/lib/api/endpoints")>()), getJob: vi.fn(), getPreview: vi.fn(), listJobAttempts: vi.fn() }));
vi.mock("@/lib/api/studio", async (original) => ({ ...(await original<typeof import("@/lib/api/studio")>()), getJobPipeline: vi.fn(), getJobScene: vi.fn(), getSimulationPackage: vi.fn(), getReviewState: vi.fn(), retryJob: vi.fn() }));

/** T-060/T-061: trang scene đọc `/pipeline`; dựng phản hồi giống backend từ tiến trình giả (bước + việc tiếp theo). */
const STUDIO_STEP_IDS = ["ST-INPUT-VALIDATE", "ST-PRIVACY-GATE", "ST-FRAME-EXTRACT", "ST-CAMERA-POSE", "ST-VISUAL-RECON", "ST-METRIC-CANONICALIZE", "ST-RGB-GEOMETRY", "ST-OBJECT-EXTRACT"];
function pipelineOf(data: unknown) {
  const progress = data as {
    job_id: string; status: string; waiting_for?: string | null;
    error?: { stage_id: string; retryable: boolean } | null;
    stages?: { stage_id: string; state: string; started_at?: string | null; completed_at?: string | null; error?: unknown }[];
  };
  const known = new Map((progress.stages ?? []).map((stage) => [stage.stage_id, stage]));
  const steps = STUDIO_STEP_IDS.map((id) => {
    const stage = known.get(id);
    const failed = progress.status === "FAILED" && progress.error?.stage_id === id;
    return {
      step_id: id, actor: id === "ST-METRIC-CANONICALIZE" ? "user" : "system",
      state: failed ? "failed" : stage?.state ?? "pending", started_at: stage?.started_at ?? null, completed_at: stage?.completed_at ?? null,
      timing_source: "inferred", phase: null, error: stage?.error ?? null, note: null,
    };
  });
  const kind = progress.status === "FAILED" ? (progress.error?.retryable ? "retry_job" : "job_failed")
    : progress.status === "CANCELLED" ? "job_cancelled"
    : progress.waiting_for === "metric_confirmation" ? "confirm_metric"
    : progress.waiting_for === "anonymization_review" ? "review_anonymization"
    : progress.status === "SUCCEEDED" ? "scene_ready" : "wait_system";
  return {
    ok: true as const,
    data: {
      notModified: false as const,
      etag: null,
      view: {
        job_id: progress.job_id, scene_revision: null, usable: false, steps, current_step: null, version: "v",
        wait: progress.status === "QUEUED" ? { kind: "queue", step_id: null, since: null } : null,
        next_action: { kind, step_id: null, owner: kind === "wait_system" ? "system" : "user", pending_count: null },
        progress: data, objectify: null, gpu: null,
      },
    },
  } as unknown as Awaited<ReturnType<typeof getJobPipeline>>;
}

const progress: JobProgress = { job_id: "job-1", status: "RUNNING", current_stage: "ST-METRIC-CANONICALIZE", attempt: 1, started_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", completed_at: null, stages: [], preview_ready: true, waiting_for: "metric_confirmation", error: null, capabilities: { can_mutate: true, can_cancel: false, can_retry: false } };
/** Thông báo của trang job nằm trong chuông ở header; mở một lần, chuông giữ mở qua các lần cập nhật. */
async function openBell() {
  fireEvent.click(await screen.findByRole("button", { name: "Thông báo của scene" }));
}
function failedProgress(retryable: boolean, previewReady = false): JobProgress {
  return {
    ...progress,
    status: "FAILED",
    waiting_for: null,
    preview_ready: previewReady,
    capabilities: { can_mutate: true, can_cancel: false, can_retry: retryable },
    error: { stage_id: "ST-VISUAL-RECON", error_code: "VISUAL_TIMEOUT", human_message: "timeout", retryable },
  };
}
function guestMe(remaining: number): Me {
  return {
    auth_required: true,
    user: { user_id: "guest-1", email: "guest@example.test", display_name: "Guest Test", role: "guest", active: true, daily_job_quota: 10 },
    quota: {
      policy_id: "guest_calendar_day_v1",
      limit: 3,
      used: 3 - remaining,
      remaining,
      window_start_utc: "2026-10-07T17:00:00Z",
      resets_at_utc: "2026-10-08T17:00:00Z",
      timezone: "Asia/Ho_Chi_Minh",
    },
  };
}
beforeEach(() => {
  vi.resetAllMocks(); history.replaceState({}, "", "/scenes/job-1?tab=progress");
  authState.me = { auth_required: false, user: null };
  authState.refresh.mockResolvedValue(undefined);
  vi.mocked(getJob).mockResolvedValue({ ok: false, error: new ApiError(404, "fixture metadata unavailable") });
  vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf(progress));
  vi.mocked(retryJob).mockResolvedValue({ job_id: "job-1", status: "QUEUED", job_manifest_checksum: "sha256:" + "c".repeat(64) });
  vi.mocked(listJobAttempts).mockResolvedValue({ ok: true, data: { job_id: "job-1", attempts: [] } });
const ref = (type: string, path: string, stage = "ST-VISUAL-RECON") => ({ artifact_type: type, schema_version: "1.0", job_id: "job-1", producer_stage: stage, artifact_uri: "artifact://jobs/job-1/attempts/a1/" + path, artifact_checksum: "sha256:" + "a".repeat(64), data_class: "derived" });
  vi.mocked(getPreview).mockResolvedValue({ ok: true, data: parsePreview({ schema_version: "1.0", artifact_type: "ReconstructionPreview", job_id: "job-1", attempt_id: "a1", source_input_checksum: "sha256:" + "b".repeat(64), format: "gaussian_sog", producer: "brush", producer_version: "fixture", metric_status: "UNCONFIRMED", coordinate_frame: "sfm_world", unit: "arbitrary", delivery_ref: ref("GaussianSOG", "scene.sog"), source_visual_ref: ref("BrushVisualArtifact", "visual.json"), camera_pose_ref: ref("CameraPoseArtifact", "poses.json", "ST-CAMERA-POSE") }, "job-1") });
});
describe("workflow scene", () => {
  it("Studio mở toàn màn hình; nút thoát quay về Tiến trình của job", async () => {
    history.replaceState({}, "", "/scenes/job-1?tab=studio");
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    await screen.findByRole("region", { name: "Canvas stub" });
    expect(screen.getByRole("main", { name: "Studio toàn màn hình" })).toHaveClass("fixed", "inset-0", "h-dvh");
    expect(screen.queryByRole("tablist", { name: "Vùng của scene" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Thoát Studio, về Tiến trình" }));
    await screen.findByRole("heading", { name: "Tiến trình xử lý" });
    expect(location.pathname).toBe("/scenes/job-1");
    expect(location.search).toContain("tab=progress");
    expect(screen.queryByRole("main", { name: "Studio toàn màn hình" })).toBeNull();
  });
  it("chuông là nơi duy nhất hiện thông báo trên mọi tab; không còn khung dưới thanh tab, trống thì nói rõ", async () => {
    vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf(failedProgress(true)));
    const view = render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    await screen.findByRole("heading", { name: "Tiến trình xử lý" }, { timeout: 3000 });
    expect(screen.queryByRole("region", { name: "Bước tiếp theo" })).toBeNull();
    expect(screen.queryByText("Xử lý chưa hoàn tất")).toBeNull();
    await openBell();
    expect(screen.getByRole("dialog", { name: "Thông báo của scene" })).toHaveTextContent("Xử lý chưa hoàn tất");
    view.unmount();

    vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf({ ...progress, status: "RUNNING", waiting_for: null, updated_at: new Date().toISOString() }));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    await screen.findByRole("heading", { name: "Tiến trình xử lý" }, { timeout: 3000 });
    await openBell();
    expect(screen.getByRole("dialog", { name: "Thông báo của scene" })).toHaveTextContent("Không có thông báo nào.");
  });
  it("Chỉnh Gaussian tạm ẩn: không có nút, và ?mode=gaussian rơi về Scene 3D thay vì mở editor", async () => {
    history.replaceState({}, "", "/scenes/job-1?tab=studio&mode=gaussian");
    vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf({ ...progress, waiting_for: null }));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    const canvas = await screen.findByRole("region", { name: "Canvas stub" }, { timeout: 3000 });
    expect(canvas).toHaveTextContent("scene");
    expect(canvas).not.toHaveTextContent("gaussian");
    expect(screen.queryByRole("button", { name: /Chỉnh Gaussian/ })).toBeNull();
  });
  it("không có ?tab= thì luôn mở Tiến trình, kể cả khi preview đã sẵn sàng hoặc job lỗi", async () => {
    for (const data of [{ ...progress, preview_ready: true }, failedProgress(true, true)]) {
      history.replaceState({}, "", "/scenes/job-1");
      vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf(data));
      const view = render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
      await screen.findByRole("heading", { name: "Tiến trình xử lý" }, { timeout: 3000 });
      expect(screen.getByRole("tab", { name: /Tiến trình/ })).toHaveAttribute("aria-selected", "true");
      expect(screen.queryByRole("region", { name: "Canvas stub" })).toBeNull();
      view.unmount();
    }
  });
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
    const failed = failedProgress(false);
    const view = render(<NextAction {...props} progress={failed} />);
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
    view.rerender(<NextAction {...props} progress={failedProgress(true)} />);
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" })); expect(props.onRetry).toHaveBeenCalledOnce();
    view.rerender(<NextAction {...props} progress={failedProgress(true)} retryState="accepted" />);
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
    expect(screen.getByText(/Đang đồng bộ lần chạy mới/)).toBeInTheDocument();
    view.rerender(<NextAction {...props} progress={progress} current="studio" mode="metric" />);
    expect(screen.queryByRole("button", { name: "Xác nhận tỉ lệ mét" })).toBeNull();
  });
  it("Guest thấy số lượt và giờ reset theo Việt Nam; nút retry bị khoá khi hết quota", () => {
    authState.me = guestMe(0);
    const props = { jobId: "job-1", current: "progress" as const, mode: "scene" as const, sceneReady: false, revision: null, busy: false, onOpen: vi.fn(), onRetry: vi.fn() };
    const failed = failedProgress(true);
    render(<NextAction {...props} progress={failed} />);
    expect(screen.getByText("Mỗi lần thử lại dùng 1 lượt chạy của khách.")).toBeInTheDocument();
    expect(screen.getByText("Guest còn 0/3 lượt hôm nay.")).toBeInTheDocument();
    const reset = screen.getByText(/Đã dùng 3\/3; đặt lại lúc/);
    expect(reset).toHaveTextContent("00:00");
    expect(reset).toHaveTextContent("09/10/2026");
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeDisabled();
  });
  it("Guest vẫn sửa scene mình sở hữu khi quota tạo job đã hết", () => {
    authState.me = guestMe(0);
    // Thông báo nằm trong chuông; nút cũng có ngay ở bước tỉ lệ mét trong timeline Tiến trình.
    const notice = render(<NextAction jobId="job-1" progress={progress} current="progress" mode="scene" sceneReady={false} revision={null} busy={false} onOpen={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Xác nhận tỉ lệ mét" })).toBeEnabled();
    notice.unmount();
    const confirm = vi.fn();
    const waiting: JobProgress = { ...progress, stages: [{ stage_id: "ST-METRIC-CANONICALIZE", state: "waiting", started_at: null, completed_at: null, error: null }] };
    const tab = render(<ProgressTab jobId="job-1" progress={waiting} info={null} busy={false} canCancel={false} onCancel={vi.fn()} onConfirmMetric={confirm} />);
    const button = screen.getByRole("button", { name: "Xác nhận tỉ lệ mét" });
    expect(button).toBeEnabled();
    expect(button.closest("li")).toHaveTextContent("Đang chờ bạn");
    fireEvent.click(button);
    expect(confirm).toHaveBeenCalledTimes(1);
    tab.unmount();
    // Không có quyền thao tác thì không có nút; bước đã xong thì chỉ còn đường "Xem giai đoạn".
    render(<ProgressTab jobId="job-1" progress={waiting} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Xác nhận tỉ lệ mét" })).toBeNull();
  });
  it("Guest không thấy retry hoặc mutation CTA trên job foreign theo capability server", () => {
    authState.me = guestMe(3);
    const foreignFailed: JobProgress = {
      ...progress,
      status: "FAILED",
      waiting_for: null,
      capabilities: { can_mutate: false, can_cancel: false, can_retry: false },
      error: { stage_id: "ST-VISUAL-RECON", error_code: "fixture", human_message: "fixture", retryable: true },
    };
    render(<NextAction jobId="job-1" progress={foreignFailed} current="progress" mode="scene" sceneReady={false} revision={null} busy={false} onOpen={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Xác nhận tỉ lệ mét" })).toBeNull();
  });
  it("Scene detail dùng capability server để giữ foreign job ở chế độ chỉ xem", async () => {
    authState.me = guestMe(3);
    history.replaceState({}, "", "/scenes/job-1?tab=studio");
    const foreignProgress = { ...progress, capabilities: { can_mutate: false, can_cancel: false, can_retry: false } };
    vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf(foreignProgress));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    await screen.findAllByText("Quyền chỉ xem");
    expect(screen.getAllByText("Quyền chỉ xem")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Chọn điểm stub" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Xác nhận tỉ lệ mét" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Huỷ xử lý" })).toBeNull();
    expect(retryJob).not.toHaveBeenCalled();
  });
  it("không mở retry chỉ vì RUNNING cũ thiếu heartbeat", () => {
    const props = { jobId: "job-1", current: "progress" as const, mode: "scene" as const, sceneReady: false, revision: null, busy: false, onOpen: vi.fn(), onRetry: vi.fn() };
    const stale: JobProgress = { ...progress, status: "RUNNING", waiting_for: null, updated_at: "2000-01-01T00:00:00Z", error: null };
    render(<NextAction {...props} progress={stale} />);
    expect(screen.getByText("Đang cập nhật trạng thái")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
  });
  it("đồng bộ retry nếu POST lỗi sau khi backend đã tạo attempt mới", async () => {
    const failed = failedProgress(true);
    const queued: JobProgress = { ...failed, status: "QUEUED", attempt: 2, updated_at: "2026-10-05T00:00:00Z", error: null };
    vi.mocked(getJobPipeline).mockResolvedValueOnce(pipelineOf(failed)).mockResolvedValue(pipelineOf(queued));
    vi.mocked(retryJob).mockRejectedValue(new ApiError(500, "Internal Server Error"));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    const button = await screen.findByRole("button", { name: "Thử lại" });
    fireEvent.click(button);
    await waitFor(() => expect(vi.mocked(retryJob)).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull());
    await openBell();
    expect(await screen.findAllByText("Đang xếp hàng")).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("bỏ qua poll FAILED cũ nếu nó trả về sau khi attempt mới đã được xác nhận", async () => {
    const failed = failedProgress(true);
    const queued: JobProgress = { ...failed, status: "QUEUED", attempt: 2, updated_at: "2026-10-05T00:00:00Z", error: null };
    const retryReceipt = deferred<Awaited<ReturnType<typeof retryJob>>>();
    const oldPoll = deferred<Awaited<ReturnType<typeof getJobPipeline>>>();
    vi.mocked(getJobPipeline)
      .mockResolvedValueOnce(pipelineOf(failed))
      .mockImplementationOnce(() => oldPoll.promise)
      .mockResolvedValueOnce(pipelineOf(queued));
    vi.mocked(retryJob).mockReturnValue(retryReceipt.promise);
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(vi.mocked(getJobPipeline)).toHaveBeenCalledTimes(2));
    retryReceipt.resolve({ job_id: "job-1", status: "QUEUED", job_manifest_checksum: "sha256:" + "c".repeat(64) });
    await waitFor(() => expect(vi.mocked(getJobPipeline)).toHaveBeenCalledTimes(3));
    await openBell();
    expect(await screen.findAllByText("Đang xếp hàng")).toHaveLength(2);
    oldPoll.resolve(pipelineOf(failed));
    await waitFor(() => expect(screen.getByText("Lần chạy 2")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
  });
  it("giữ nút retry ẩn nếu POST đã được nhận nhưng poll mới vẫn trả attempt FAILED cũ", async () => {
    const failed = failedProgress(true);
    vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf(failed));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(vi.mocked(retryJob)).toHaveBeenCalledOnce());
    await openBell();
    expect(await screen.findByText("Đang đồng bộ lần chạy mới")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
  });
  it("giữ retry khả dụng nếu POST bị từ chối và máy chủ xác nhận attempt FAILED", async () => {
    const failed = failedProgress(true);
    vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf(failed));
    vi.mocked(retryJob).mockRejectedValue(new ApiError(409, "Job đã đổi trạng thái; tải lại tiến trình"));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Job đã đổi trạng thái"));
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });
  it("refresh quota sau 429 từ tab khác và khoá retry theo /auth/me mới", async () => {
    authState.me = guestMe(1);
    authState.refresh.mockImplementation(async () => { authState.me = guestMe(0); });
    const failed = failedProgress(true);
    vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf(failed));
    vi.mocked(retryJob).mockRejectedValue(new ApiError(429, JSON.stringify({ code: "guest_daily_job_quota_exceeded" })));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(authState.refresh).toHaveBeenCalledOnce());
    expect(await screen.findByRole("alert")).toHaveTextContent("hết lượt Guest");
    // Nút ở bước lỗi bị khoá kèm lý do; chuông hiện số lượt còn lại và nút của nó cũng khoá.
    const rowRetry = screen.getByRole("button", { name: "Thử lại" });
    expect(rowRetry).toBeDisabled();
    expect(rowRetry).toHaveAttribute("title", expect.stringContaining("hết lượt Guest"));
    await openBell();
    expect(screen.getByText("Guest còn 0/3 lượt hôm nay.")).toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: "Thử lại" })) expect(button).toBeDisabled();
  });
  it("refresh quota sau khi máy chủ chấp nhận manual Retry của Guest", async () => {
    authState.me = guestMe(1);
    const failed = failedProgress(true);
    const queued: JobProgress = { ...failed, status: "QUEUED", attempt: 2, updated_at: "2026-10-05T00:00:00Z", error: null };
    vi.mocked(getJobPipeline).mockResolvedValueOnce(pipelineOf(failed)).mockResolvedValue(pipelineOf(queued));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(authState.refresh).toHaveBeenCalledOnce());
    expect(vi.mocked(retryJob)).toHaveBeenCalledOnce();
  });
  it("mở lại retry khi POST gặp lỗi hạ tầng nhưng trạng thái hiện tại vẫn FAILED", async () => {
    const failed = failedProgress(true);
    vi.mocked(getJobPipeline).mockResolvedValue(pipelineOf(failed));
    vi.mocked(retryJob).mockRejectedValue(new ApiError(500, "gateway failed"));
    render(<PageTitleProvider><ScenePage jobId="job-1" /></PageTitleProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("trạng thái mới nhất vẫn là FAILED"));
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
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
    render(<NextAction jobId="job-1" progress={done} current="studio" mode="scene" sceneReady revision={scene.scene_revision} busy={false} onOpen={vi.fn()} onRetry={vi.fn()} />);
    expect(await screen.findByText("Tách theo vật chưa thành công")).toBeInTheDocument();
    // Việc chọn tiếp nằm ngay ở hàng bước "Tách vật thể" của tab Tiến trình, không phải trong Studio.
    expect(screen.getByRole("button", { name: "Xem bước tách vật thể" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mở Studio để chọn" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Mở tạo gói mô phỏng" })).toBeNull();
  });
});
