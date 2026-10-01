/** Proof component theo fixture; không thay browser/GPU hoặc real worker acceptance. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PageTitleProvider, crumbsFor } from "@/features/shell/Breadcrumbs";
import { canInspect, inspectionStage } from "@/features/studio/inspection";
import { StageInspectionPage } from "@/features/studio/inspection/StageInspectionPage";
import { PipelineTimeline } from "@/features/studio/PipelineTimeline";
import { STUDIO_STAGES } from "@/features/studio/stages";
import { ApiError } from "@/lib/api/client";
import { getJob, getProject, listJobArtifacts } from "@/lib/api/endpoints";
import { getJobProgress } from "@/lib/api/studio";
import type { JobManifest, Project } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";

vi.mock("@/lib/api/endpoints", async (original) => ({ ...(await original<typeof import("@/lib/api/endpoints")>()), getJob: vi.fn(), getProject: vi.fn(), listJobArtifacts: vi.fn() }));
vi.mock("@/lib/api/studio", async (original) => ({ ...(await original<typeof import("@/lib/api/studio")>()), getJobProgress: vi.fn() }));
vi.mock("@/features/studio/StageViewer", () => ({ StageViewer: ({ stageId }: { stageId: string }) => <div>View: {stageId}</div> }));
vi.mock("@/features/studio/inspection/StageSceneWorkspace", () => ({ StageSceneWorkspace: ({ stageId }: { stageId: string }) => <div>Scene: {stageId}</div> }));

const sha = `sha256:${"a".repeat(64)}`;
const progress: JobProgress = {
  job_id: "job-a", status: "SUCCEEDED", current_stage: "ST-OBJECT-EXTRACT", attempt: 1,
  started_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:10:00Z", completed_at: "2026-10-01T00:10:00Z",
  stages: STUDIO_STAGES.map((stage) => ({ stage_id: stage.id, state: "succeeded", started_at: null, completed_at: "2026-10-01T00:10:00Z", error: null })), preview_ready: true, waiting_for: null, error: null,
};
const project: Project = { project_id: "project-a", name: "Kho A", source_type: "upload", input_manifest_checksum: sha, source_rights_attestation: { rights_to_use_confirmed: true, anonymization_confirmed: true }, privacy: { project_id: "project-a", result: "PRELIMINARY_SCREENED", input_manifest_checksum: sha, inspection_scope: "sampled", unresolved_finding_count: 0, dispatch_allowed: true, block_reason: null }, input_video: { original_name: "kho.mp4", media_type: "video/mp4", size_bytes: 100 }, created_at: null };
const job: JobManifest = { schema_version: "1.0", job_id: "job-a", project_id: "project-a", status: "SUCCEEDED", current_stage: "ST-OBJECT-EXTRACT", scene_revision: "rev-001", seed: 1, input_manifest_checksum: sha, config_checksum: sha, runtime_manifest_checksum: sha, job_manifest_checksum: sha, stage_artifacts: [], started_at: null, completed_at: null };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getJobProgress).mockResolvedValue({ ok: true, data: progress });
  vi.mocked(getJob).mockResolvedValue({ ok: true, data: job });
  vi.mocked(getProject).mockResolvedValue({ ok: true, data: project });
  vi.mocked(listJobArtifacts).mockResolvedValue({ ok: true, data: { job_id: "job-a", artifacts: [], excluded_artifact_count: 0 } });
});
function show(stageId: string) { return render(<PageTitleProvider><StageInspectionPage jobId="job-a" stageId={stageId} /></PageTitleProvider>); }

describe("Inspect theo giai đoạn", () => {
  it("timeline chỉ chọn được bước xong; selection mở link đúng stage, mẫu không tạo link job", () => {
    const stages = STUDIO_STAGES.map((stage, n) => ({ stage_id: stage.id, state: n === 0 ? "succeeded" as const : "pending" as const, seconds: null, fraction: null }));
    const view = render(<PipelineTimeline stages={stages} stageList={STUDIO_STAGES} jobId="job-a" />);
    expect(screen.queryByRole("link", { name: "Xem giai đoạn" })).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /Kiểm tra video/ }));
    expect(screen.getByRole("link", { name: "Xem giai đoạn" })).toHaveAttribute("href", "/scenes/job-a/stages/ST-INPUT-VALIDATE");
    view.rerender(<PipelineTimeline stages={stages} stageList={STUDIO_STAGES} />);
    expect(screen.queryByRole("link", { name: "Xem giai đoạn" })).toBeNull();
  });

  it("tám giai đoạn đều có mapping; waiting metric không được Inspect", () => {
    for (const stage of STUDIO_STAGES) expect(inspectionStage(stage.id)).toBe(stage);
    expect(inspectionStage("ST-ISAAC-VALIDATE")).toBeUndefined();
    const waiting: JobProgress = { ...progress, status: "RUNNING", waiting_for: "metric_confirmation", stages: progress.stages.map((stage) => stage.stage_id === "ST-METRIC-CANONICALIZE" ? { ...stage, state: "waiting" } : stage) };
    expect(canInspect(waiting, "ST-METRIC-CANONICALIZE")).toBe(false);
    expect(canInspect(waiting, "ST-VISUAL-RECON")).toBe(true);
  });

  it("link trực tiếp tới bước chưa xong không tải output hoặc mount viewer", async () => {
    vi.mocked(getJobProgress).mockResolvedValue({ ok: true, data: { ...progress, stages: progress.stages.map((stage) => ({ ...stage, state: "pending" })) } });
    show("ST-VISUAL-RECON");
    expect(await screen.findByText(/chưa hoàn tất trong lần chạy/)).toBeInTheDocument();
    expect(getJob).not.toHaveBeenCalled();
    expect(listJobArtifacts).not.toHaveBeenCalled();
    expect(screen.queryByText(/Scene: ST-VISUAL/)).toBeNull();
  });

  it.each(STUDIO_STAGES)("nội dung khác nhau cho $id, viewport chính và output panel thu gọn", async (stage) => {
    show(stage.id);
    await screen.findByText("Đã xử lý xong");
    const index = STUDIO_STAGES.findIndex((item) => item.id === stage.id);
    if (index === 0) expect(screen.getByText("Đầu vào đã kiểm tra")).toBeInTheDocument();
    else if (index === 1) expect(screen.getByText("Quyền riêng tư của đầu vào")).toBeInTheDocument();
    else if (index < 4) expect(await screen.findByText(`View: ${stage.id}`)).toBeInTheDocument();
    else expect(await screen.findByText(`Scene: ${stage.id}`)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Về Tiến trình" })).toHaveAttribute("href", "/scenes/job-a?tab=progress");
    expect(screen.queryByRole("complementary")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Thông tin đầu ra" }));
    expect(screen.getByRole("complementary", { name: "Thông tin đầu ra" })).toBeInTheDocument();
  });

  it("lỗi API có retry, không bật viewport hoặc xem lỗi thành thành công", async () => {
    vi.mocked(getJobProgress).mockResolvedValueOnce({ ok: false, error: new ApiError(503, "Mất kết nối") });
    show("ST-VISUAL-RECON");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(getJob).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByText("Scene: ST-VISUAL-RECON")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Mất kết nối")).toBeNull());
  });

  it("breadcrumb giữ scene parent và tên giai đoạn", () => {
    expect(crumbsFor("/scenes/job-a/stages/ST-RGB-GEOMETRY", "Kho A")).toEqual([{ label: "Scenes", href: "/scenes" }, { label: "Kho A", href: "/scenes/job-a?tab=progress" }, { label: "Hình học & collision" }]);
  });
});
