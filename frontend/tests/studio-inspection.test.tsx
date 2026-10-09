/** Proof component theo fixture; không thay browser/GPU hoặc real worker acceptance. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PageTitleProvider, crumbsFor } from "@/features/shell/Breadcrumbs";
import { canInspect, inspectionStage } from "@/features/studio/inspection";
import { LidarCalibrationQAStage } from "@/features/studio/inspection/LidarCalibrationQAStage";
import { LidarOdometryStage } from "@/features/studio/inspection/LidarOdometryStage";
import { StageInspectionPage } from "@/features/studio/inspection/StageInspectionPage";
import { PipelineTimeline } from "@/features/studio/PipelineTimeline";
import { LIDAR_CALIBRATION_QA_STAGE, LIDAR_ODOMETRY_STAGE, STUDIO_STAGES, stagesFor } from "@/features/studio/stages";
import { ApiError } from "@/lib/api/client";
import { getJob, getProject, listJobArtifacts } from "@/lib/api/endpoints";
import { getJobProgress } from "@/lib/api/studio";
import type { JobManifest, ProductArtifactRef, Project } from "@/lib/contracts/api";
import type { JobProgress } from "@/lib/contracts/studio";

vi.mock("@/lib/api/endpoints", async (original) => ({ ...(await original<typeof import("@/lib/api/endpoints")>()), getJob: vi.fn(), getProject: vi.fn(), listJobArtifacts: vi.fn() }));
vi.mock("@/lib/api/studio", async (original) => ({ ...(await original<typeof import("@/lib/api/studio")>()), getJobProgress: vi.fn() }));
vi.mock("@/features/studio/StageViewer", () => ({ StageViewer: ({ stageId }: { stageId: string }) => <div>View: {stageId}</div> }));
vi.mock("@/features/studio/inspection/StageSceneWorkspace", () => ({ StageSceneWorkspace: ({ stageId }: { stageId: string }) => <div>Scene: {stageId}</div> }));

const sha = `sha256:${"a".repeat(64)}`;
const trajectoryReference: ProductArtifactRef = {
  artifact_type: "EstimatedTrajectoryArtifact",
  schema_version: "1.0",
  artifact_uri: "artifact://jobs/job-a/attempts/attempt-a/rec17/trajectory.json",
  artifact_checksum: sha,
  data_class: "derived",
  producer_stage: LIDAR_ODOMETRY_STAGE.id,
  job_id: "job-a",
};
const trajectoryArtifact = {
  artifact_type: "EstimatedTrajectoryArtifact",
  job_id: "job-a",
  trajectory_origin: "estimated",
  runtime_qualification_status: "qualified",
  diagnostics: {
    scan_count: 2,
    valid_pose_count: 2,
    coverage_ratio: 1,
    timestamp_gap_threshold_seconds: 0.5,
    timestamp_gap_count: 0,
    maximum_timestamp_gap_seconds: 0.25,
    absolute_drift_status: "not_measured",
  },
};
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
afterEach(() => vi.unstubAllGlobals());
function show(stageId: string) { return render(<PageTitleProvider><StageInspectionPage jobId="job-a" stageId={stageId} /></PageTitleProvider>); }

describe("Inspect theo giai đoạn", () => {
  it("timeline chỉ chọn được bước xong; selection mở link đúng stage, mẫu không tạo link job", () => {
    const stages = STUDIO_STAGES.map((stage, n) => ({ stage_id: stage.id, state: n === 0 ? "succeeded" as const : "pending" as const, seconds: null, fraction: null }));
    const view = render(<PipelineTimeline stages={stages} stageList={STUDIO_STAGES} jobId="job-a" />);
    // Nút hiện sẵn trên đúng bước đã xong, không cần mở chi tiết trước; bước chưa chạy không có nút.
    const links = screen.getAllByRole("link", { name: /^Xem giai đoạn/ });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/scenes/job-a/stages/ST-INPUT-VALIDATE");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    view.rerender(<PipelineTimeline stages={stages} stageList={STUDIO_STAGES} />);
    expect(screen.queryByRole("link", { name: /^Xem giai đoạn/ })).toBeNull();
  });

  it("bước cần người dùng thao tác có nút hiện sẵn tại hàng của nó; bước đã xong thì chỉ còn Xem giai đoạn", () => {
    const confirm = vi.fn();
    const review = vi.fn();
    const stages = STUDIO_STAGES.map((stage) => ({ stage_id: stage.id, state: stage.id === "ST-METRIC-CANONICALIZE" ? "waiting" as const : stage.id === "ST-FRAME-EXTRACT" ? "running" as const : "pending" as const, seconds: null, fraction: null }));
    const actions = [
      { stageId: "ST-METRIC-CANONICALIZE" as const, label: "Xác nhận tỉ lệ mét", onClick: confirm },
      { stageId: "ST-FRAME-EXTRACT" as const, label: "Xem bản đã che", onClick: review },
    ];
    const view = render(<PipelineTimeline stages={stages} stageList={STUDIO_STAGES} jobId="job-a" stageActions={actions} />);
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận tỉ lệ mét" }));
    fireEvent.click(screen.getByRole("button", { name: "Xem bản đã che" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(review).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Xác nhận tỉ lệ mét" }).closest("li")).toHaveTextContent("Đang chờ bạn");

    const done = stages.map((stage) => ({ ...stage, state: "succeeded" as const }));
    view.rerender(<PipelineTimeline stages={done} stageList={STUDIO_STAGES} jobId="job-a" stageActions={actions} />);
    expect(screen.queryByRole("button", { name: "Xác nhận tỉ lệ mét" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Xem bản đã che" })).toBeNull();
    expect(screen.getByRole("link", { name: /^Xem giai đoạn: Xác nhận tỉ lệ mét/ })).toHaveAttribute("href", "/scenes/job-a/stages/ST-METRIC-CANONICALIZE");
  });

  it("timeline cho mở report QA dù structural check làm job dừng", () => {
    const stage = LIDAR_CALIBRATION_QA_STAGE;
    const stages = [{ stage_id: stage.id, state: "failed" as const, seconds: null, fraction: null }];
    render(<PipelineTimeline stages={stages} stageList={[stage]} jobId="job-a" />);

    expect(screen.getByRole("link", { name: /^Xem giai đoạn/ })).toHaveAttribute(
      "href",
      "/scenes/job-a/stages/ST-LIDAR-CALIBRATION-QA",
    );
  });

  it("tám giai đoạn đều có mapping; waiting metric không được Inspect", () => {
    for (const stage of STUDIO_STAGES) expect(inspectionStage(stage.id)).toBe(stage);
    expect(inspectionStage("ST-ISAAC-VALIDATE")).toBeUndefined();
    const waiting: JobProgress = { ...progress, status: "RUNNING", waiting_for: "metric_confirmation", stages: progress.stages.map((stage) => stage.stage_id === "ST-METRIC-CANONICALIZE" ? { ...stage, state: "waiting" } : stage) };
    expect(canInspect(waiting, "ST-METRIC-CANONICALIZE")).toBe(false);
    expect(canInspect(waiting, "ST-VISUAL-RECON")).toBe(true);
    expect(inspectionStage("ST-LIDAR-CALIBRATION-QA")?.title).toBe("QA calibration LiDAR");
    expect(inspectionStage(LIDAR_ODOMETRY_STAGE.id)).toBe(LIDAR_ODOMETRY_STAGE);
    expect(stagesFor([LIDAR_ODOMETRY_STAGE.id]).map((stage) => stage.id).slice(3, 4)).toEqual([
      LIDAR_ODOMETRY_STAGE.id,
    ]);
    const lidarStages = stagesFor(["ST-LIDAR-INGEST", "ST-LIDAR-CALIBRATION-QA"]);
    expect(lidarStages.map((stage) => stage.id).slice(3, 5)).toEqual([
      "ST-LIDAR-INGEST", "ST-LIDAR-CALIBRATION-QA",
    ]);
  });

  it("shows estimated poses as local diagnostics while world, floor and alignment remain pending", async () => {
    const reference: ProductArtifactRef = {
      artifact_type: "EstimatedTrajectoryConsumerEvidence",
      schema_version: "1.0",
      artifact_uri: "artifact://jobs/job-a/attempts/attempt-a/lidar-odometry/consumer-evidence.json",
      artifact_checksum: sha,
      data_class: "derived",
      producer_stage: LIDAR_ODOMETRY_STAGE.id,
      job_id: "job-a",
    };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          artifact_type: "EstimatedTrajectoryConsumerEvidence",
          job_id: "job-a",
          recipe_group: "R6",
          ingest_binding: { source_scan_file_ids: ["scan-1", "scan-2"] },
          trajectory_ref: trajectoryReference,
          odometry_runtime_id: "kiss-icp-python",
          odometry_runtime_version: "1.3.0",
          odometry_profile_checksum: sha,
          runtime_qualification_status: "qualified",
          world_frame_status: "pending_world_from_map_confirmation",
          floor_status: "pending_floor_and_up_axis_evidence",
          alignment_status: "not_registered",
        }),
      })
      .mockResolvedValueOnce({ ok: true, json: async () => trajectoryArtifact }));
    render(<LidarOdometryStage jobId="job-a" artifacts={[reference]} />);

    expect(await screen.findByText(/local odometry map/)).toBeInTheDocument();
    expect(screen.getByText("pending_world_from_map_confirmation")).toBeInTheDocument();
    expect(screen.getByText("pending_floor_and_up_axis_evidence")).toBeInTheDocument();
    expect(screen.getByText("not_registered")).toBeInTheDocument();
    expect(screen.getByText(/2\/2/)).toBeInTheDocument();
    expect(screen.getByText("not_measured")).toBeInTheDocument();
    expect(screen.getByText(/không dùng làm LiDAR canonical hoặc collision source/)).toBeInTheDocument();
  });

  it("shows the source-bound fused map while keeping canonical consumers pending", async () => {
    const reference: ProductArtifactRef = {
      artifact_type: "EstimatedTrajectoryProductEvidence",
      schema_version: "1.0",
      artifact_uri: "artifact://jobs/job-a/attempts/attempt-a/lidar-odometry/product-evidence.json",
      artifact_checksum: sha,
      data_class: "derived",
      producer_stage: LIDAR_ODOMETRY_STAGE.id,
      job_id: "job-a",
    };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          artifact_type: "EstimatedTrajectoryProductEvidence",
          schema_version: "1.0",
          job_id: "job-a",
          consumer_evidence: {
            artifact_type: "EstimatedTrajectoryConsumerEvidence",
            job_id: "job-a",
            recipe_group: "R6",
            ingest_binding: { source_scan_file_ids: ["scan-1", "scan-2"] },
            trajectory_ref: trajectoryReference,
            odometry_runtime_id: "kiss-icp-python",
            odometry_runtime_version: "1.3.0",
            odometry_profile_checksum: sha,
            runtime_qualification_status: "qualified",
            world_frame_status: "pending_world_from_map_confirmation",
            floor_status: "pending_floor_and_up_axis_evidence",
            alignment_status: "not_registered",
          },
          map_evidence: {
            artifact_type: "EstimatedTrajectoryMapEvidence",
            job_id: "job-a",
            map_frame_id: "odom-map-01",
            map_status: "ready",
            point_count: 1234,
            diagnostic_code: null,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ...trajectoryArtifact,
          diagnostics: {
            ...trajectoryArtifact.diagnostics,
            scan_count: 2,
            valid_pose_count: 1,
            coverage_ratio: 0.5,
            timestamp_gap_count: 1,
            maximum_timestamp_gap_seconds: 1.25,
          },
        }),
      }));
    render(<LidarOdometryStage jobId="job-a" artifacts={[reference]} />);

    expect(await screen.findByText("Map ready")).toBeInTheDocument();
    expect(screen.getByText(/1\.234 points · odom-map-01/)).toBeInTheDocument();
    expect(screen.getByText("pending_world_from_map_confirmation")).toBeInTheDocument();
    expect(screen.getByText("pending_floor_and_up_axis_evidence")).toBeInTheDocument();
    expect(screen.getByText("not_registered")).toBeInTheDocument();
    expect(screen.getByText(/1\/2/)).toBeInTheDocument();
    expect(screen.getByText(/ngưỡng 0,5 s · lớn nhất 1,25 s/)).toBeInTheDocument();
    expect(screen.getByText(/Có khoảng timestamp vượt ngưỡng/)).toBeInTheDocument();
    expect(screen.getByText(/Một số scan chưa có pose được ước lượng/)).toBeInTheDocument();
  });

  it("does not show diagnostics whose scan count differs from the accepted source binding", async () => {
    const reference: ProductArtifactRef = {
      artifact_type: "EstimatedTrajectoryConsumerEvidence",
      schema_version: "1.0",
      artifact_uri: "artifact://jobs/job-a/attempts/attempt-a/lidar-odometry/consumer-evidence.json",
      artifact_checksum: sha,
      data_class: "derived",
      producer_stage: LIDAR_ODOMETRY_STAGE.id,
      job_id: "job-a",
    };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          artifact_type: "EstimatedTrajectoryConsumerEvidence",
          job_id: "job-a",
          recipe_group: "R6",
          ingest_binding: { source_scan_file_ids: ["scan-1", "scan-2"] },
          trajectory_ref: trajectoryReference,
          odometry_runtime_id: "kiss-icp-python",
          odometry_runtime_version: "1.3.0",
          odometry_profile_checksum: sha,
          runtime_qualification_status: "qualified",
          world_frame_status: "pending_world_from_map_confirmation",
          floor_status: "pending_floor_and_up_axis_evidence",
          alignment_status: "not_registered",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ...trajectoryArtifact,
          diagnostics: {
            ...trajectoryArtifact.diagnostics,
            scan_count: 3,
          },
        }),
      }));
    render(<LidarOdometryStage jobId="job-a" artifacts={[reference]} />);

    expect(await screen.findByText(/Không tải được diagnostics trajectory/)).toBeInTheDocument();
    expect(screen.queryByText("Pose coverage")).not.toBeInTheDocument();
  });

  it("báo trạng thái chẩn đoán, hiển thị overlay nhưng không cấp collision eligibility", async () => {
    const reference = (artifact_type: string, name: string): ProductArtifactRef => ({
      artifact_type, schema_version: "1.0", artifact_uri: `artifact://jobs/job-a/lidar-calibration-qa/${name}`,
      artifact_checksum: sha, data_class: "derived", producer_stage: "ST-LIDAR-CALIBRATION-QA", job_id: "job-a",
    });
    const report = {
      schema_version: "1.0", package_ref: reference("LidarPackageRecord", "package.json"), result: "INCONCLUSIVE",
      observability: "INSUFFICIENT", sampled_frame_count: 3, matched_frame_count: 2, observable_frame_count: 0,
      projected_point_count: 0, overlap_point_count: 0, overlap_fraction: null, maximum_timestamp_residual_sec: null,
      findings: [{ code: "INSUFFICIENT_MATCHED_FRAMES", severity: "inconclusive", detail: "Thiếu pose ghép được.", remediation: "Kiểm tra timing." }],
      overlay_refs: [reference("LidarCalibrationQAOverlay", "overlay.svg")],
      diagnostic_projection_ref: reference("LidarCalibrationProjectionEvidence", "projection-evidence.json"),
      report_checksum: sha,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => report }));
    render(<LidarCalibrationQAStage jobId="job-a" artifacts={[reference("LidarCalibrationQAReport", "report.json")]} />);

    expect(await screen.findByText("Tóm tắt phép chiếu")).toBeInTheDocument();
    expect(screen.getByText("Collision eligibility: không")).toBeInTheDocument();
    expect(screen.getByAltText("Frame RGB với các điểm chiếu LiDAR màu cyan")).toBeInTheDocument();
    expect(screen.getByText("Thiếu pose ghép được.")).toBeInTheDocument();
  });

  it("cho inspect report structural FAIL để người dùng thấy cách sửa trước khi chạy lại", async () => {
    const stageId = LIDAR_CALIBRATION_QA_STAGE.id;
    const stageError = {
      stage_id: stageId,
      error_code: "LIDAR_CALIBRATION_QA_FAILED",
      human_message: "LiDAR calibration QA found structural input inconsistencies; correct the source and create a new job.",
      retryable: false,
      details: { action: "Correct coordinate units and create a new job" },
    };
    const qaProgress = {
      ...progress,
      status: "FAILED" as const,
      current_stage: stageId,
      stages: [
        ...progress.stages,
        {
          ...progress.stages[0],
          stage_id: stageId,
          state: "failed" as const,
          completed_at: "2026-10-01T00:05:00Z",
          error: stageError,
        },
      ],
    };
    const reference = (artifact_type: string, name: string): ProductArtifactRef => ({
      artifact_type, schema_version: "1.0", artifact_uri: `artifact://jobs/job-a/lidar-calibration-qa/${name}`,
      artifact_checksum: sha, data_class: "derived", producer_stage: stageId, job_id: "job-a",
    });
    const reportRef = reference("LidarCalibrationQAReport", "report.json");
    const report = {
      schema_version: "1.0", package_ref: reference("LidarPackageRecord", "package.json"), result: "FAIL",
      observability: "UNAVAILABLE", sampled_frame_count: 0, matched_frame_count: 0, observable_frame_count: 0,
      projected_point_count: 0, overlap_point_count: 0, overlap_fraction: null, maximum_timestamp_residual_sec: null,
      findings: [{ code: "COORDINATE_UNIT_UNSUPPORTED", severity: "fail", detail: "Đơn vị tọa độ là mm.", remediation: "Khai báo lại đơn vị mét rồi tạo job mới." }],
      overlay_refs: [], diagnostic_projection_ref: null, report_checksum: sha,
    };
    vi.mocked(getJobProgress).mockResolvedValue({ ok: true, data: qaProgress });
    vi.mocked(getJob).mockResolvedValue({
      ok: true,
      data: {
        ...job,
        status: "FAILED",
        current_stage: stageId,
        stage_artifacts: [{
          stage_id: stageId, status: "FAILED", artifact_type: reportRef.artifact_type,
          artifact_uri: reportRef.artifact_uri, artifact_checksum: reportRef.artifact_checksum,
          data_class: "derived", started_at: "2026-10-01T00:04:00Z", completed_at: "2026-10-01T00:05:00Z",
          error: stageError,
        }],
      },
    });
    vi.mocked(listJobArtifacts).mockResolvedValue({
      ok: true,
      data: { job_id: "job-a", artifacts: [reportRef], excluded_artifact_count: 0 },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => report }));
    show(stageId);

    expect(await screen.findByText("Tóm tắt phép chiếu")).toBeInTheDocument();
    expect(screen.getByText("QA thất bại")).toBeInTheDocument();
    expect(screen.getByText("Có lỗi cấu trúc")).toBeInTheDocument();
    expect(screen.getByText("Đơn vị tọa độ là mm.")).toBeInTheDocument();
    expect(screen.getByText("Collision eligibility: không")).toBeInTheDocument();
  });

  it("từ chối report QA tham chiếu package thuộc job khác", async () => {
    const reference = (artifact_type: string, jobId: string): ProductArtifactRef => ({
      artifact_type, schema_version: "1.0", artifact_uri: `artifact://jobs/${jobId}/lidar-calibration-qa/report.json`,
      artifact_checksum: sha, data_class: "derived", producer_stage: "ST-LIDAR-CALIBRATION-QA", job_id: jobId,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: "1.0", package_ref: reference("LidarPackageRecord", "job-other"), result: "INCONCLUSIVE",
        observability: "UNAVAILABLE", sampled_frame_count: 0, matched_frame_count: 0, observable_frame_count: 0,
        projected_point_count: 0, overlap_point_count: 0, overlap_fraction: null, maximum_timestamp_residual_sec: null,
        findings: [], overlay_refs: [], diagnostic_projection_ref: null, report_checksum: sha,
      }),
    }));
    render(<LidarCalibrationQAStage jobId="job-a" artifacts={[reference("LidarCalibrationQAReport", "job-a")]} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/không đúng contract hoặc thuộc job khác/);
    expect(screen.queryByText("Collision eligibility: không")).toBeNull();
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
