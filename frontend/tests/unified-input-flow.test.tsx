import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UnifiedInputFlow } from "@/features/studio/UnifiedInputFlow";
import { VideoPreparationError } from "@/lib/media/video-normalization-core";
import type { AssemblyUploadResponse, InputResolutionReport, InputResolutionCandidate, RuntimeCapabilityRecord } from "@/lib/contracts/inputAssembly";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  create: vi.fn(),
  revise: vi.fn(),
  resolve: vi.fn(),
  run: vi.fn(),
  importGaussian: vi.fn(),
  stage: vi.fn(),
  getStaged: vi.fn(),
  uploadAssembly: vi.fn(),
  prepareVideo: vi.fn(),
  uploadPrepared: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  usePathname: () => "/new",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/features/studio/AuthProvider", () => ({
  useAuth: () => ({
    me: { auth_required: false, user: { user_id: "user-1", display_name: "Reviewer", role: "reviewer" } },
    refresh: mocks.refresh,
  }),
}));
vi.mock("@/features/studio/useProcessingForm", () => ({
  useProcessingForm: () => ({ options: null, values: null, evaluation: null, error: null, loading: false, evaluating: false }),
}));
vi.mock("@/lib/media/video-normalization", () => ({ prepareVideoForUpload: mocks.prepareVideo }));
vi.mock("@/lib/api/studio", () => ({ uploadPreparedVideo: mocks.uploadPrepared }));
vi.mock("@/lib/api/inputAssemblies", () => ({
  createInputAssembly: mocks.create,
  getStagedInputUpload: mocks.getStaged,
  importGaussianFromAssembly: mocks.importGaussian,
  resolveInputAssembly: mocks.resolve,
  reviseInputAssembly: mocks.revise,
  runInputAssembly: mocks.run,
  stageExistingInputUpload: mocks.stage,
  uploadAssemblyFile: mocks.uploadAssembly,
}));

const runtime: RuntimeCapabilityRecord = {
  capability_key: "R1",
  status: "qualified",
  runtime_id: "video-worker",
  runtime_version: "1",
  qualification_evidence_checksum: `sha256:${"1".repeat(64)}`,
  reason_codes: [],
};

function videoCandidate(candidateId: string, fileId: string, state: "ready" | "needs_input", code?: string): InputResolutionCandidate {
  return {
    candidate_kind: "video_recipe",
    candidate_id: candidateId,
    recipe_group: "R1",
    state,
    bindings: [{ binding_id: `binding-${fileId}`, role: "rgb_video", file_ids: [fileId] }],
    excluded_file_ids: [],
    trajectory_origin: "not_required",
    required_facts: code ? [{ code, description: code === "VIDEO_SELECTION_REQUIRED" ? "Choose one video." : "Exclude unused input.", related_file_ids: [fileId] }] : [],
    diagnostics: [],
    runtime,
  };
}

function sensorRecipeCandidate(
  candidateId: string,
  recipeGroup: "R4" | "R6",
  state: "ready" | "pending_verification",
): InputResolutionCandidate {
  const estimated = recipeGroup === "R6";
  const runtimeStatus = estimated ? "wired_unqualified" : "qualified";
  return {
    candidate_kind: "video_recipe",
    candidate_id: candidateId,
    recipe_group: recipeGroup,
    state,
    bindings: [
      { binding_id: `${candidateId}-rgb`, role: "rgb_video", file_ids: ["file-upload-video"] },
      { binding_id: `${candidateId}-scan`, role: "lidar_scan", file_ids: ["file-scan"] },
      ...(estimated ? [{ binding_id: `${candidateId}-scan-times`, role: "lidar_scan_times" as const, file_ids: ["file-scan-times"] }] : []),
      ...(!estimated ? [{ binding_id: `${candidateId}-trajectory`, role: "sensor_trajectory" as const, file_ids: ["file-trajectory"] }] : []),
      { binding_id: `${candidateId}-calibration`, role: "camera_lidar_calibration", file_ids: ["file-calibration"] },
      { binding_id: `${candidateId}-rgb-times`, role: "rgb_frame_times", file_ids: ["file-rgb-times"] },
    ],
    excluded_file_ids: [],
    trajectory_origin: estimated ? "estimated" : "supplied",
    required_facts: [],
    diagnostics: estimated ? [{
      code: "ODOMETRY_RUNTIME_UNQUALIFIED",
      severity: "warning",
      description: "R6 depends on an odometry runtime that is wired but not qualified.",
      related_file_ids: ["file-scan"],
    }] : [],
    runtime: {
      capability_key: recipeGroup,
      status: runtimeStatus,
      runtime_id: estimated ? null : "qualified-r4-worker",
      runtime_version: estimated ? null : "1",
      qualification_evidence_checksum: estimated ? null : `sha256:${"2".repeat(64)}`,
      reason_codes: [],
    },
  };
}

function report(state: InputResolutionReport["state"], candidates: InputResolutionCandidate[], recommended: string | null): InputResolutionReport {
  return {
    schema_version: "1.0",
    assembly_id: "assembly-1",
    assembly_revision: 1,
    assembly_checksum: `sha256:${"2".repeat(64)}`,
    resolver_version: "assembly-input-resolver-v2",
    runtime_registry_checksum: `sha256:${"3".repeat(64)}`,
    state,
    candidates,
    recommended_candidate_id: recommended,
    missing_facts: candidates.flatMap((candidate) => candidate.required_facts),
    diagnostics: [],
    report_checksum: `sha256:${"4".repeat(64)}`,
  };
}

function staged(uploadId: string, name: string): AssemblyUploadResponse {
  return {
    upload_id: uploadId,
    source_file: {
      original_name: name,
      media_type: "video/mp4",
      size_bytes: 128,
      checksum: `sha256:${"a".repeat(64)}`,
      artifact_uri: `artifact://jobs/${uploadId}/input/source.mp4`,
      data_class: "product_input",
    },
    staged_files: [{
      file_id: `file-${uploadId}`,
      upload_id: uploadId,
      source_file: {
        original_name: name,
        media_type: "video/mp4",
        size_bytes: 128,
        checksum: `sha256:${"a".repeat(64)}`,
        artifact_uri: `artifact://jobs/${uploadId}/input/source.mp4`,
        data_class: "product_input",
      },
      observed_format: "video_mp4",
      archive_member: null,
      role_evidence: [],
    }],
    probes: [],
    received_at: "2026-10-08T00:00:00Z",
  };
}

function stagedTimestamp(uploadId: string, name: string): AssemblyUploadResponse {
  const result = staged(uploadId, name);
  const source = { ...result.source_file, media_type: "text/plain" };
  return {
    ...result,
    source_file: source,
    staged_files: result.staged_files.map((item) => ({
      ...item,
      source_file: source,
      observed_format: "timestamp_rows",
      role_evidence: [],
    })),
  };
}

function stagedGaussian(uploadId: string, name: string): AssemblyUploadResponse {
  const result = staged(uploadId, name);
  return {
    ...result,
    source_file: { ...result.source_file, media_type: "application/octet-stream" },
    staged_files: result.staged_files.map((item) => ({ ...item, observed_format: "gaussian_sog" })),
  };
}

function snapshot(revision: number) {
  return {
    schema_version: "1.0" as const,
    assembly_id: "assembly-1",
    revision,
    owner_id: "user-1",
    created_at: "2026-10-08T00:00:00Z",
    requested_intent: "video_reconstruction" as const,
    files: [],
    bindings: [],
    declarations: {
      same_scene: null,
      cloud_state: null,
      coordinate_unit: null,
      lidar_frame_id: null,
      world_frame_id: null,
      trajectory_convention: null,
      clock_relation: null,
      clock_offset_seconds: null,
    },
    video_preparation_verification: null,
    assembly_checksum: `sha256:${"5".repeat(64)}`,
  };
}

describe("unified input flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    mocks.prepareVideo.mockResolvedValue({ dispose: vi.fn(), file: new File(["prepared"], "normalized.mp4", { type: "video/mp4" }), frameMapFile: new File(["map"], "frame-map.jsonl"), manifest: {} });
    let nextUpload = 0;
    mocks.uploadPrepared.mockImplementation((_prepared, options) => {
      const uploadId = `upload-${++nextUpload}`;
      options.onProgress(1);
      return { abort: vi.fn(), promise: Promise.resolve({ upload_id: uploadId }) };
    });
    mocks.stage.mockImplementation(async (uploadId: string) => staged(uploadId, `${uploadId}.mp4`));
    mocks.getStaged.mockImplementation(async (uploadId: string) => staged(uploadId, `${uploadId}.mp4`));
    mocks.create.mockResolvedValue(snapshot(1));
    mocks.revise.mockImplementation(async (_assemblyId: string, revision: number) => snapshot(revision + 1));
    mocks.resolve
      .mockResolvedValueOnce({ report: report("needs_input", [videoCandidate("r1-a", "file-upload-1", "needs_input", "VIDEO_SELECTION_REQUIRED"), videoCandidate("r1-b", "file-upload-2", "needs_input", "VIDEO_SELECTION_REQUIRED")], null) })
      .mockResolvedValueOnce({ report: report("needs_input", [videoCandidate("r1-a", "file-upload-1", "needs_input", "UNUSED_INPUT_DISPOSITION_REQUIRED")], null) })
      .mockResolvedValueOnce({ report: report("ready", [videoCandidate("r1-a", "file-upload-1", "ready")], "r1-a") });
    mocks.run.mockResolvedValue({ project: { project_id: "project-1" }, job: { job_id: "job-1" } });
    mocks.importGaussian.mockResolvedValue({ imported_scene: { import_id: "import-1" }, intent_checksum: `sha256:${"6".repeat(64)}` });
  });

  it("prepares each dropped video before upload and requires an explicit choice for ambiguous videos", async () => {
    const { container } = render(<UnifiedInputFlow />);
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    const first = new File(["first"], "video-a.mp4", { type: "video/mp4" });
    const second = new File(["second"], "video-b.mov", { type: "video/quicktime" });
    fireEvent.change(fileInput!, { target: { files: [first, second] } });

    fireEvent.click(await screen.findByRole("button", { name: "Tải file đã chọn lên" }));
    expect(await screen.findAllByText("Đã xác minh")).toHaveLength(2);
    expect(mocks.prepareVideo).toHaveBeenCalledTimes(2);
    expect(mocks.prepareVideo.mock.calls[0][0]).toMatchObject({ preset: "720p", source: first });
    expect(mocks.uploadPrepared).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(JSON.parse(window.sessionStorage.getItem("r2s:input-assembly:v1:user-1") ?? "{}").uploads).toHaveLength(2));

    fireEvent.click(screen.getByRole("button", { name: "Phân tích input" }));
    expect(await screen.findByText(/Cần bổ sung lựa chọn/)).toBeInTheDocument();
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ upload_ids: ["upload-1", "upload-2"] }));
    expect(mocks.run).not.toHaveBeenCalled();
    expect(screen.getByText("Input: video-a.mp4")).toBeInTheDocument();
    expect(screen.getByText("Input: video-b.mov")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Chọn hướng này" })[0]);
    await waitFor(() => expect(mocks.revise).toHaveBeenCalledWith("assembly-1", 1, expect.objectContaining({ bindings: [{ binding_id: "binding-file-upload-1", role: "rgb_video", file_ids: ["file-upload-1"] }] })));
    expect(await screen.findAllByText(/Exclude unused input/)).toHaveLength(2);

    fireEvent.click(screen.getByLabelText("Đưa video-b.mov vào assembly"));
    fireEvent.click(screen.getByRole("button", { name: "Phân tích input" }));
    expect(await screen.findByText("Recipe đã được resolver xác nhận là có thể dispatch")).toBeInTheDocument();
    expect(mocks.run).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Người/đơn vị sở hữu dữ liệu"), { target: { value: "Nhóm P-087" } });
    fireEvent.change(screen.getByLabelText("Nguồn dữ liệu"), { target: { value: "self_collected_no_pii" } });
    fireEvent.change(screen.getByLabelText("Mục đích sử dụng"), { target: { value: "Tái dựng scene" } });
    fireEvent.click(screen.getByLabelText(/Tôi có quyền sử dụng dữ liệu/));
    fireEvent.click(screen.getByLabelText(/Video không có khuôn mặt/));
    fireEvent.click(screen.getByLabelText(/Tôi hiểu dữ liệu và kết quả/));
    fireEvent.click(screen.getByRole("button", { name: /Tạo job theo recipe này/ }));

    await waitFor(() => expect(mocks.run).toHaveBeenCalledWith("assembly-1", expect.objectContaining({
      revision: 3,
      resolution_checksum: `sha256:${"4".repeat(64)}`,
      candidate_id: "r1-a",
      name: "video-a",
      attestation: expect.objectContaining({ declared_owner: "Nhóm P-087", rights_to_use_confirmed: true }),
    })));
    expect(mocks.push).toHaveBeenCalledWith("/scenes/job-1");
    expect(window.sessionStorage.getItem("r2s:input-assembly:v1:user-1")).toBeNull();
  });

  it("asks before dropping incompatible audio, and never drops it on its own", async () => {
    mocks.prepareVideo.mockRejectedValueOnce(new VideoPreparationError("audio_omission_required", "Audio tracks with negative starting timestamps cannot be preserved."));
    const { container } = render(<UnifiedInputFlow />);
    const phone = new File(["phone"], "IMG_3911.mp4", { type: "video/mp4" });
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, { target: { files: [phone] } });
    fireEvent.click(await screen.findByRole("button", { name: "Tải file đã chọn lên" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Âm thanh của video không giữ nguyên được/);
    expect(mocks.prepareVideo.mock.calls[0][0]).toMatchObject({ omitAudioWithConsent: false });
    expect(mocks.uploadPrepared).not.toHaveBeenCalled();
    expect(mocks.uploadAssembly).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Bỏ âm thanh và chuẩn bị lại" }));
    expect(await screen.findByText("Đã xác minh")).toBeInTheDocument();
    expect(mocks.prepareVideo.mock.calls[1][0]).toMatchObject({ omitAudioWithConsent: true, source: phone });
    expect(mocks.uploadPrepared).toHaveBeenCalledTimes(1);
    expect(mocks.uploadAssembly).not.toHaveBeenCalled();
  });

  it("explains an undecodable codec in Vietnamese and uploads the original only on an explicit choice", async () => {
    mocks.prepareVideo.mockRejectedValueOnce(new VideoPreparationError("unsupported_codec", "This browser cannot decode the selected video's codec."));
    mocks.uploadAssembly.mockImplementation((file: File, _account: string, onProgress: (value: number) => void) => {
      onProgress(1);
      return { abort: vi.fn(), promise: Promise.resolve(staged("upload-raw", file.name)) };
    });
    const { container } = render(<UnifiedInputFlow />);
    const hevc = new File(["hevc"], "IMG_3911.mp4", { type: "video/mp4" });
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, { target: { files: [hevc] } });
    fireEvent.click(await screen.findByRole("button", { name: "Tải file đã chọn lên" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/không giải mã được codec/);
    expect(screen.queryByRole("button", { name: "Bỏ âm thanh và chuẩn bị lại" })).toBeNull();
    expect(mocks.uploadAssembly).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Tải video gốc không nén/ }));
    expect(await screen.findByText("Đã xác minh")).toBeInTheDocument();
    expect(mocks.uploadAssembly).toHaveBeenCalledTimes(1);
    expect(mocks.uploadAssembly.mock.calls[0][0]).toBe(hevc);
    expect(mocks.prepareVideo).toHaveBeenCalledTimes(1);
    expect(mocks.uploadPrepared).not.toHaveBeenCalled();
  });

  it("shows unqualified R6 diagnostics while keeping the supplied R4 recipe as a usable fallback", async () => {
    window.sessionStorage.setItem("r2s:input-assembly:v1:user-1", JSON.stringify({
      schema_version: 1,
      account_id: "user-1",
      uploads: [{ upload_id: "upload-video", original_name: "warehouse.mp4", included: true, preset: "720p" }],
      scan_order: [],
      intent: "video_reconstruction",
      scene_name: "Warehouse",
    }));
    mocks.getStaged.mockResolvedValue(staged("upload-video", "warehouse.mp4"));
    const supplied = sensorRecipeCandidate("r4-supplied", "R4", "ready");
    const estimated = sensorRecipeCandidate("r6-estimated", "R6", "pending_verification");
    mocks.resolve.mockReset().mockResolvedValue({ report: report("ready", [supplied, estimated], supplied.candidate_id) });

    render(<UnifiedInputFlow />);
    expect(await screen.findByText("warehouse.mp4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Phân tích input" }));

    expect(await screen.findByText("R6 depends on an odometry runtime that is wired but not qualified.")).toBeInTheDocument();
    expect(screen.getByText("Runtime: wired_unqualified")).toBeInTheDocument();
    expect(screen.getByText("Recipe đã được resolver xác nhận là có thể dispatch")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Người/đơn vị sở hữu dữ liệu"), { target: { value: "Nhóm P-087" } });
    fireEvent.change(screen.getByLabelText("Nguồn dữ liệu"), { target: { value: "self_collected_no_pii" } });
    fireEvent.change(screen.getByLabelText("Mục đích sử dụng"), { target: { value: "Tái dựng scene" } });
    fireEvent.click(screen.getByLabelText(/Tôi có quyền sử dụng dữ liệu/));
    fireEvent.click(screen.getByLabelText(/Video không có khuôn mặt/));
    fireEvent.click(screen.getByLabelText(/Tôi hiểu dữ liệu và kết quả/));
    expect(screen.getByRole("button", { name: /Tạo job theo recipe này/ })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Tạo job theo recipe này/ }));

    await waitFor(() => expect(mocks.run).toHaveBeenCalledWith("assembly-1", expect.objectContaining({
      candidate_id: supplied.candidate_id,
      revision: 1,
    })));
  });

  it("requires explicit timestamp sensor roles and preserves separate RGB and LiDAR units", async () => {
    mocks.resolve.mockReset().mockResolvedValue({ report: report("needs_input", [], null) });
    mocks.uploadAssembly.mockReturnValue({
      promise: Promise.resolve(stagedTimestamp("upload-times", "sensor-times.txt")),
      abort: vi.fn(),
    });

    const { container } = render(<UnifiedInputFlow />);
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, { target: { files: [
      new File(["video"], "warehouse.mp4", { type: "video/mp4" }),
      new File(["0\n0.1\n"], "sensor-times.txt", { type: "text/plain" }),
    ] } });

    fireEvent.click(await screen.findByRole("button", { name: "Tải file đã chọn lên" }));
    expect(await screen.findAllByText("Đã xác minh")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Phân tích input" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create.mock.calls[0][0].bindings).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ role: "rgb_frame_times" })]),
    );

    fireEvent.change(screen.getByLabelText("File timestamp của frame RGB"), { target: { value: "file-upload-times" } });
    fireEvent.change(screen.getByLabelText("Đơn vị timestamp RGB"), { target: { value: "milliseconds" } });
    fireEvent.click(screen.getByRole("button", { name: "Phân tích input" }));

    await waitFor(() => expect(mocks.revise).toHaveBeenCalledWith("assembly-1", 1, expect.objectContaining({
      bindings: [expect.objectContaining({ role: "rgb_frame_times", file_ids: ["file-upload-times"] })],
      declarations: expect.objectContaining({
        timestamp_unit: null,
        rgb_timestamp_unit: expect.objectContaining({ value: "milliseconds", provenance: "declared" }),
        lidar_timestamp_unit: null,
      }),
    })));
  });

  it("restores and revalidates upload refs only for the authenticated account", async () => {
    window.sessionStorage.setItem("r2s:input-assembly:v1:user-1", JSON.stringify({
      schema_version: 1,
      account_id: "user-1",
      uploads: [{ upload_id: "upload-owned", original_name: "warehouse.mp4", included: true, preset: "720p" }],
      scan_order: [],
      intent: null,
    }));
    window.sessionStorage.setItem("r2s:input-assembly:v1:user-2", JSON.stringify({
      schema_version: 1,
      account_id: "user-2",
      uploads: [{ upload_id: "upload-other", original_name: "other.mp4", included: true, preset: "720p" }],
      scan_order: [],
      intent: null,
    }));

    render(<UnifiedInputFlow />);

    expect(await screen.findByText("warehouse.mp4")).toBeInTheDocument();
    expect(mocks.getStaged).toHaveBeenCalledTimes(1);
    expect(mocks.getStaged).toHaveBeenCalledWith("upload-owned");
    expect(screen.queryByText("other.mp4")).not.toBeInTheDocument();
  });

  it("routes a staged SOG through the durable view import without exposing continuation", async () => {
    mocks.uploadAssembly.mockReturnValue({ promise: Promise.resolve(stagedGaussian("upload-sog", "warehouse.sog")), abort: vi.fn() });
    const viewCandidate: InputResolutionCandidate = {
      candidate_kind: "gaussian_view_import",
      candidate_id: "gaussian-view-1",
      source_file_id: "file-upload-sog",
      source_format: "gaussian_sog",
      state: "ready",
      excluded_file_ids: [],
      required_facts: [],
      diagnostics: [],
      runtime: {
        capability_key: "gaussian_sog_view",
        status: "qualified",
        runtime_id: "sog-view",
        runtime_version: "1",
        qualification_evidence_checksum: `sha256:${"7".repeat(64)}`,
        reason_codes: [],
      },
    };
    mocks.resolve.mockReset().mockResolvedValue({ report: report("ready", [viewCandidate], viewCandidate.candidate_id) });

    const { container } = render(<UnifiedInputFlow />);
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(fileInput!, { target: { files: [new File(["sog"], "warehouse.sog", { type: "application/octet-stream" })] } });
    fireEvent.click(await screen.findByRole("button", { name: "Tải file đã chọn lên" }));
    await waitFor(() => expect(mocks.uploadAssembly).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Đã xác minh")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Phân tích input" }));
    expect(await screen.findByText("Recipe đã được resolver xác nhận là có thể dispatch")).toBeInTheDocument();
    expect(screen.getByText("Import chỉ đưa scene 3DGS vào viewer hiện tại. Chưa có luồng xử lý tiếp scene đã import.")).toBeInTheDocument();
    expect(screen.queryByText(/Xử lý tiếp/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Tên scene"), { target: { value: "Kho SOG" } });
    fireEvent.click(screen.getByRole("button", { name: "Mở scene 3DGS" }));

    await waitFor(() => expect(mocks.importGaussian).toHaveBeenCalledWith("assembly-1", expect.objectContaining({
      revision: 1,
      candidate_id: "gaussian-view-1",
      name: "Kho SOG",
    })));
    expect(mocks.run).not.toHaveBeenCalled();
    expect(mocks.push).toHaveBeenCalledWith("/imports/import-1");
  });
});
