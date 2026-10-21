import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegistrationPanel } from "@/features/studio/scene/RegistrationPanel";
import { ApiError } from "@/lib/api/client";
import type { Me } from "@/lib/api/auth";
import {
  cancelRegistrationOperation,
  confirmRegistrationOperation,
  enqueueRegistration,
  getRegistrationOperation,
  getRegistrationOperationInspection,
  prepareRegistration,
  type RegistrationOperation,
  type RegistrationOperationInspection,
  type RegistrationOverlayPreview,
  type RegistrationPreparation,
  type RegistrationRequestPayload,
  type JsonObject,
} from "@/lib/api/registration";

const authState = vi.hoisted(() => ({
  me: { auth_required: true, user: { user_id: "guest-1", email: "guest@example.test", display_name: "Guest", role: "guest", active: true, daily_job_quota: 10 } } as Me,
}));

vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => authState }));
vi.mock("@/lib/api/registration", async (original) => {
  const actual = await original<typeof import("@/lib/api/registration")>();
  return {
    ...actual,
    cancelRegistrationOperation: vi.fn(),
    confirmRegistrationOperation: vi.fn(),
    enqueueRegistration: vi.fn(),
    getRegistrationOperation: vi.fn(),
    getRegistrationOperationInspection: vi.fn(),
    prepareRegistration: vi.fn(),
  };
});

const request: RegistrationRequestPayload = {
  request_id: "registration-request-1",
  requested_by: "guest-1",
  target_project_id: "project-1",
  target_job_id: "job-1",
  expected_scene_revision: "rev-001",
  request_checksum: `sha256:${"a".repeat(64)}`,
  source: { mode: "registered_map", target_job_id: "job-1" },
};

const ready: RegistrationPreparation = {
  request,
  preflight: { request_checksum: request.request_checksum, state: "READY", findings: [] },
};

function operation(state: RegistrationOperation["state"], updates: Partial<RegistrationOperation> = {}): RegistrationOperation {
  return {
    operation_id: request.request_id,
    job_id: "job-1",
    state,
    operation_checksum: `sha256:${"7".repeat(64)}`,
    attempt: 1,
    created_at: "2026-10-09T00:00:00Z",
    updated_at: "2026-10-09T00:00:00Z",
    proposal_ref: null,
    qa_report_ref: null,
    cancellation_requested: false,
    confirmed_candidate_id: null,
    confirmed_by_user_id: null,
    confirmed_at: null,
    ...updates,
  };
}

function inspection(): RegistrationOperationInspection {
  const proposalChecksum = `sha256:${"c".repeat(64)}`;
  const sourceGeometry = {
    artifact_type: "LiDARGeometryArtifact",
    artifact_uri: "artifact://jobs/job-1/lidar/geometry.json",
    artifact_checksum: `sha256:${"e".repeat(64)}`,
  };
  const targetGeometry = {
    artifact_type: "RgbGeometry",
    artifact_uri: "artifact://jobs/job-1/rgb/geometry.json",
    artifact_checksum: `sha256:${"f".repeat(64)}`,
  };
  const firstTransform = {
    parent_frame: "world",
    local_frame: "lidar-map",
    translation_xyz: [1, 2, 0],
    rotation_quaternion_xyzw: [0, 0, 0, 1],
  };
  const secondTransform = {
    ...firstTransform,
    translation_xyz: [4, 5, 0],
  };
  const overlay = (
    candidateId: string,
    transform: typeof firstTransform,
    x: number,
    scale: number,
  ): RegistrationOverlayPreview => ({
    operation_id: request.request_id,
    job_id: "job-1",
    request_checksum: request.request_checksum,
    source_input_checksum: `sha256:${"b".repeat(64)}`,
    source_geometry_ref: sourceGeometry,
    target_rgb_geometry_ref: targetGeometry,
    target_scene_revision: "rev-001",
    candidate_id: candidateId,
    transform_target_from_source: transform,
    rgb_scale_factor: scale,
    bounds_min_xy_m: [-10, -10],
    bounds_max_xy_m: [10, 10],
    source_in_roi_point_count: 1,
    target_in_roi_point_count: 1,
    source_points_xy_world_m: [[x, 1]],
    target_points_xy_world_m: [[x + 1, 2]],
    sample_cap_per_cloud: 512,
    diagnostic_only: true,
    preview_checksum: `sha256:${"9".repeat(64)}`,
  });
  return {
    operation_id: request.request_id,
    job_id: "job-1",
    expected_scene_revision: "rev-001",
    current_scene_revision: "rev-002",
    proposal: {
      schema_version: "1.0",
      artifact_type: "RegistrationProposalArtifact",
      job_id: "job-1",
      target_scene_revision: "rev-001",
      proposal_checksum: proposalChecksum,
      request_checksum: request.request_checksum,
      source_input_checksum: `sha256:${"b".repeat(64)}`,
      profile_checksum: `sha256:${"a".repeat(64)}`,
      source_geometry_ref: sourceGeometry,
      target_rgb_geometry_ref: targetGeometry,
      state: "PROPOSED",
      candidates: [
        {
          candidate_id: "candidate-1",
          score: 0.95,
          rgb_scale_factor: 1.25,
          transform_target_from_source: firstTransform,
        },
        {
          candidate_id: "candidate-2",
          score: 0.82,
          rgb_scale_factor: 1.1,
          transform_target_from_source: secondTransform,
        },
      ],
    },
    qa_report: {
      schema_version: "1.0",
      artifact_type: "RegistrationQAReport",
      job_id: "job-1",
      target_scene_revision: "rev-001",
      proposal_checksum: proposalChecksum,
      report_checksum: `sha256:${"d".repeat(64)}`,
      result: "INCONCLUSIVE",
      source_coverage_ratio: 0.85,
      target_coverage_ratio: 0.75,
      bidirectional_p95_residual_m: 0.02,
      regions: [{
        region_id: "aisle-1",
        source_coverage_ratio: 0.8,
        target_coverage_ratio: 0.7,
        correspondence_count: 28,
        p95_residual_m: 0.03,
      }],
      findings: ["UNQUALIFIED_PROFILE"],
    },
    overlay_previews: [
      overlay("candidate-1", firstTransform, 1, 1.25),
      overlay("candidate-2", secondTransform, 4, 1.1),
    ],
  };
}

function qualifiedInspection(): RegistrationOperationInspection {
  const value = inspection();
  const proposal = value.proposal as JsonObject;
  const candidates = Array.isArray(proposal.candidates) ? proposal.candidates : [];
  const qaReport = value.qa_report as JsonObject;
  return {
    ...value,
    current_scene_revision: "rev-001",
    proposal: {
      ...proposal,
      selected_candidate_id: "candidate-1",
      candidates: candidates.map((candidate) => typeof candidate === "object"
        && candidate !== null && !Array.isArray(candidate) && candidate.candidate_id === "candidate-1"
        ? { ...candidate, rgb_scale_factor: null }
        : candidate),
    },
    qa_report: {
      ...qaReport,
      result: "PASS",
      candidate_id: "candidate-1",
      findings: [],
    },
    overlay_previews: value.overlay_previews.map((preview) => preview.candidate_id === "candidate-1"
      ? { ...preview, rgb_scale_factor: null }
      : preview),
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  window.sessionStorage.clear();
  authState.me = {
    auth_required: true,
    user: { user_id: "guest-1", email: "guest@example.test", display_name: "Guest", role: "guest", active: true, daily_job_quota: 10 },
  };
});

describe("registration panel", () => {
  it("starts only a READY request and reports the server proposal without applying it", async () => {
    vi.mocked(prepareRegistration).mockResolvedValue(ready);
    vi.mocked(enqueueRegistration).mockResolvedValue(operation("QUEUED"));
    vi.mocked(getRegistrationOperation)
      .mockResolvedValueOnce({ ok: true, data: operation("PROPOSED", { proposal_ref: { artifact_type: "RegistrationProposalArtifact" }, qa_report_ref: { artifact_type: "RegistrationQAReport" } }) })
      .mockResolvedValue({ ok: true, data: operation("PROPOSED", { proposal_ref: { artifact_type: "RegistrationProposalArtifact" }, qa_report_ref: { artifact_type: "RegistrationQAReport" } }) });
    vi.mocked(getRegistrationOperationInspection).mockResolvedValue({ ok: true, data: inspection() });

    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));
    expect(await screen.findByText(/đạt kiểm tra ban đầu/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu căn chỉnh" }));

    await screen.findByText("Có đề xuất cần kiểm tra");
    expect(prepareRegistration).toHaveBeenCalledWith("job-1", "rev-001");
    expect(enqueueRegistration).toHaveBeenCalledWith("job-1", request);
    expect(screen.getByText(/Chưa áp dụng gì/)).toBeInTheDocument();
    expect(window.sessionStorage.getItem("real2sim:rgb-lidar-registration:v1:guest-1:job-1")).toContain(request.request_id);
    expect(await screen.findByText("INCONCLUSIVE")).toBeInTheDocument();
    expect(screen.getByText(/candidate-1.*điểm xếp hạng 0\.950/)).toBeInTheDocument();
    expect(screen.getAllByText(/Transform: T_world_from_lidar-map/)).toHaveLength(2);
    expect(screen.getByText(/Giả thuyết scale RGB: 1\.250×/)).toBeInTheDocument();
    expect(screen.getByText(/aisle-1: phủ nguồn 80\.0%, phủ đích 70\.0%,\s*28 correspondence, P95 0\.030 m/)).toBeInTheDocument();
    expect(screen.getByText(/Dịch chuyển xyz \(m\): 1\.000, 2\.000, 0\.000/)).toBeInTheDocument();
    expect(screen.getByText(/Đề xuất này thuộc phiên bản scene cũ/)).toBeInTheDocument();
    const firstOverlay = await screen.findByRole("img", { name: /candidate-1/ });
    expect(firstOverlay.querySelectorAll("circle")).toHaveLength(2);
    expect(screen.getByText(/không thay cho kiểm tra/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Phương án chồng chiếu" }), { target: { value: "candidate-2" } });
    expect(await screen.findByRole("img", { name: /candidate-2/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xác nhận alignment candidate QA" })).toBeDisabled();
    expect(confirmRegistrationOperation).not.toHaveBeenCalled();
    expect(getRegistrationOperationInspection).toHaveBeenCalledWith("job-1", request.request_id, expect.any(AbortSignal));
  });

  it("confirms only the selected QA-qualified candidate and stores the server decision", async () => {
    const confirmed = operation("CONFIRMED", {
      confirmed_candidate_id: "candidate-1",
      confirmed_by_user_id: "guest-1",
      confirmed_at: "2026-10-09T00:05:00Z",
    });
    vi.mocked(prepareRegistration).mockResolvedValue(ready);
    vi.mocked(enqueueRegistration).mockResolvedValue(operation("QUEUED"));
    vi.mocked(getRegistrationOperation).mockResolvedValue({
      ok: true,
      data: operation("PROPOSED", { proposal_ref: { artifact_type: "RegistrationProposalArtifact" }, qa_report_ref: { artifact_type: "RegistrationQAReport" } }),
    });
    vi.mocked(getRegistrationOperationInspection).mockResolvedValue({ ok: true, data: qualifiedInspection() });
    vi.mocked(confirmRegistrationOperation).mockResolvedValue(confirmed);

    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));
    await screen.findByRole("button", { name: "Bắt đầu căn chỉnh" });
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu căn chỉnh" }));

    const confirmButton = await screen.findByRole("button", { name: "Xác nhận alignment candidate QA" });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    fireEvent.click(confirmButton);

    await screen.findByText(/Đã xác nhận candidate-1/);
    expect(confirmRegistrationOperation).toHaveBeenCalledWith("job-1", request.request_id, {
      expected_operation_checksum: `sha256:${"7".repeat(64)}`,
      expected_scene_revision: "rev-001",
      candidate_id: "candidate-1",
    });
    expect(screen.getByText(/đang lưu kết quả căn chỉnh/)).toBeInTheDocument();
  });

  it("does not enqueue when the server reports insufficient preflight", async () => {
    vi.mocked(prepareRegistration).mockResolvedValue({
      request,
      preflight: { request_checksum: request.request_checksum, state: "INSUFFICIENT", findings: ["FLOOR_UNCERTAIN"] },
    });

    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));

    expect(await screen.findByText("Chưa thể căn chỉnh.")).toBeInTheDocument();
    expect(screen.getByText("Bằng chứng mặt sàn chưa chắc chắn.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bắt đầu căn chỉnh" })).not.toBeInTheDocument();
    expect(enqueueRegistration).not.toHaveBeenCalled();
  });

  it("fails closed when preparation returns a request for a different actor", async () => {
    vi.mocked(prepareRegistration).mockResolvedValue({
      ...ready,
      request: { ...request, requested_by: "other-user" },
    });

    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));

    expect(await screen.findByText("Máy chủ chưa xử lý được yêu cầu. Hãy thử lại.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bắt đầu căn chỉnh" })).not.toBeInTheDocument();
    expect(enqueueRegistration).not.toHaveBeenCalled();
  });

  it("replays the same sealed request and idempotency key after an uncertain response and reload", async () => {
    vi.mocked(prepareRegistration).mockResolvedValue(ready);
    vi.mocked(enqueueRegistration)
      .mockRejectedValueOnce(new ApiError(0, "network disconnected"))
      .mockResolvedValueOnce(operation("QUEUED"));
    vi.mocked(getRegistrationOperation).mockResolvedValue({ ok: true, data: operation("RUNNING") });

    const first = render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));
    await screen.findByText(/đạt kiểm tra ban đầu/);
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu căn chỉnh" }));
    await screen.findByRole("button", { name: "Gửi lại cùng yêu cầu" });
    first.unmount();

    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    await waitFor(() => expect(enqueueRegistration).toHaveBeenCalledTimes(2));
    expect(enqueueRegistration).toHaveBeenNthCalledWith(1, "job-1", request);
    expect(enqueueRegistration).toHaveBeenNthCalledWith(2, "job-1", request);
    await screen.findByText("Đang căn chỉnh");
  });

  it("blocks a prepared request when the target revision changes", async () => {
    vi.mocked(prepareRegistration).mockResolvedValue(ready);
    const view = render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));
    await screen.findByRole("button", { name: "Bắt đầu căn chỉnh" });

    view.rerender(<RegistrationPanel jobId="job-1" sceneRevision="rev-002" canMutateJob />);
    expect(screen.getByText(/Scene đã có phiên bản mới. Hãy kiểm tra lại trước khi chạy/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bắt đầu căn chỉnh" })).not.toBeInTheDocument();
    expect(enqueueRegistration).not.toHaveBeenCalled();
  });

  it("keeps read-only users from starting or cancelling registration", () => {
    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob={false} />);
    expect(screen.getByText(/chỉ có quyền xem/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kiểm tra dữ liệu" })).not.toBeInTheDocument();
    expect(prepareRegistration).not.toHaveBeenCalled();
  });

  it("waits for the worker's cancellation acknowledgement", async () => {
    vi.mocked(prepareRegistration).mockResolvedValue(ready);
    vi.mocked(enqueueRegistration).mockResolvedValue(operation("RUNNING"));
    vi.mocked(getRegistrationOperation).mockResolvedValue({ ok: true, data: operation("RUNNING") });
    vi.mocked(cancelRegistrationOperation).mockResolvedValue(operation("RUNNING", { cancellation_requested: true }));

    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));
    await screen.findByRole("button", { name: "Bắt đầu căn chỉnh" });
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu căn chỉnh" }));
    fireEvent.click(await screen.findByRole("button", { name: "Hủy căn chỉnh" }));

    await screen.findByRole("button", { name: "Đang chờ xác nhận hủy" });
    expect(cancelRegistrationOperation).toHaveBeenCalledWith("job-1", request.request_id);
    expect(screen.getByText(/^Đang dừng…$/)).toBeInTheDocument();
  });

  it("aborts an in-flight status read when the panel unmounts", async () => {
    let statusSignal: AbortSignal | undefined;
    vi.mocked(prepareRegistration).mockResolvedValue(ready);
    vi.mocked(enqueueRegistration).mockResolvedValue(operation("RUNNING"));
    vi.mocked(getRegistrationOperation).mockImplementation((_jobId, _operationId, signal) => {
      statusSignal = signal;
      return new Promise(() => {});
    });

    const view = render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));
    await screen.findByRole("button", { name: "Bắt đầu căn chỉnh" });
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu căn chỉnh" }));
    await waitFor(() => expect(getRegistrationOperation).toHaveBeenCalled());
    expect(statusSignal?.aborted).toBe(false);

    view.unmount();
    expect(statusSignal?.aborted).toBe(true);
  });

  it("aborts an in-flight proposal inspection when the panel unmounts", async () => {
    let inspectionSignal: AbortSignal | undefined;
    window.sessionStorage.setItem(
      "real2sim:rgb-lidar-registration:v1:guest-1:job-1",
      JSON.stringify({ version: 1, expected_scene_revision: "rev-001", operation_id: request.request_id }),
    );
    vi.mocked(getRegistrationOperation).mockResolvedValue({
      ok: true,
      data: operation("PROPOSED", {
        proposal_ref: { artifact_type: "RegistrationProposalArtifact" },
        qa_report_ref: { artifact_type: "RegistrationQAReport" },
      }),
    });
    vi.mocked(getRegistrationOperationInspection).mockImplementation((_jobId, _operationId, signal) => {
      inspectionSignal = signal;
      return new Promise(() => {});
    });

    const view = render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob={false} />);
    await waitFor(() => expect(getRegistrationOperationInspection).toHaveBeenCalled());
    expect(inspectionSignal?.aborted).toBe(false);

    view.unmount();
    expect(inspectionSignal?.aborted).toBe(true);
  });
});
