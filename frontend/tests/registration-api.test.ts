import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmRegistrationOperation,
  enqueueRegistration,
  isRegistrationOperationActive,
  isRegistrationOperationPollable,
  parseRegistrationOperationInspection,
  parseRegistrationOperation,
  parseRegistrationPreparation,
  parseRegistrationRequest,
  type RegistrationRequestPayload,
} from "@/lib/api/registration";

const request: RegistrationRequestPayload = {
  request_id: "registration-request-1",
  requested_by: "user-1",
  target_project_id: "project-1",
  target_job_id: "job-1",
  expected_scene_revision: "rev-001",
  request_checksum: `sha256:${"a".repeat(64)}`,
  source: { mode: "static_cloud", target_job_id: "job-1" },
};

describe("RGB-LiDAR registration API parsers", () => {
  afterEach(() => vi.restoreAllMocks());

  it("accepts a derived estimated-trajectory map source", () => {
    expect(parseRegistrationRequest({
      ...request,
      source: { mode: "estimated_trajectory_map", target_job_id: "job-1" },
    }).source.mode).toBe("estimated_trajectory_map");
  });

  it("requires preflight to bind the exact sealed request checksum", () => {
    expect(() => parseRegistrationPreparation({
      request,
      preflight: { request_checksum: `sha256:${"b".repeat(64)}`, state: "READY", findings: [] },
    })).toThrow(/preflight không khớp request/);
  });

  it("rejects operation status for another job or an unknown state", () => {
    const operation = {
      operation_id: request.request_id,
      job_id: "other-job",
      state: "QUEUED",
      attempt: 0,
      created_at: "2026-10-09T00:00:00Z",
      updated_at: "2026-10-09T00:00:00Z",
      proposal_ref: null,
      qa_report_ref: null,
      cancellation_requested: false,
    };
    expect(() => parseRegistrationOperation(operation, "job-1")).toThrow(/contract/);
    expect(() => parseRegistrationOperation({ ...operation, job_id: "job-1", state: "MYSTERY" }, "job-1")).toThrow(/contract/);
  });

  it("requires durable confirmation identity on confirmed operation responses", () => {
    const confirmed = {
      operation_id: request.request_id,
      job_id: "job-1",
      state: "CONFIRMED",
      operation_checksum: `sha256:${"b".repeat(64)}`,
      attempt: 1,
      created_at: "2026-10-09T00:00:00Z",
      updated_at: "2026-10-09T00:01:00Z",
      proposal_ref: null,
      qa_report_ref: null,
      cancellation_requested: false,
      confirmed_candidate_id: "candidate-1",
      confirmed_by_user_id: "user-1",
      confirmed_at: "2026-10-09T00:01:00Z",
    };
    expect(parseRegistrationOperation(confirmed, "job-1").confirmed_candidate_id).toBe("candidate-1");
    expect(() => parseRegistrationOperation({ ...confirmed, confirmed_by_user_id: null }, "job-1"))
      .toThrow(/contract/);
    expect(() => parseRegistrationOperation({ ...confirmed, operation_checksum: "broken" }, "job-1"))
      .toThrow(/contract/);
  });

  it("accepts bound stale inspection evidence but rejects cross-job and mismatched QA payloads", () => {
    const proposalChecksum = `sha256:${"c".repeat(64)}`;
    const inspection = {
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
      },
      qa_report: {
        schema_version: "1.0",
        artifact_type: "RegistrationQAReport",
        job_id: "job-1",
        target_scene_revision: "rev-001",
        proposal_checksum: proposalChecksum,
        report_checksum: `sha256:${"d".repeat(64)}`,
      },
    };

    expect(parseRegistrationOperationInspection(inspection, "job-1", request.request_id).current_scene_revision)
      .toBe("rev-002");
    expect(() => parseRegistrationOperationInspection({ ...inspection, job_id: "other-job" }, "job-1", request.request_id))
      .toThrow(/operation, job/);
    expect(() => parseRegistrationOperationInspection({
      ...inspection,
      qa_report: { ...inspection.qa_report, proposal_checksum: `sha256:${"e".repeat(64)}` },
    }, "job-1", request.request_id)).toThrow(/operation, job/);
  });

  it("accepts only bounded overlays bound to the exact inspection candidate", () => {
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
    const candidateTransform = {
      parent_frame: "world",
      local_frame: "lidar-map",
      translation_xyz: [1, 2, 0],
      rotation_quaternion_xyzw: [0, 0, 0, 1],
    };
    const proposal = {
      schema_version: "1.0",
      artifact_type: "RegistrationProposalArtifact",
      job_id: "job-1",
      input_mode: "static_cloud",
      target_scene_revision: "rev-001",
      proposal_checksum: proposalChecksum,
      request_checksum: request.request_checksum,
      source_input_checksum: `sha256:${"b".repeat(64)}`,
      profile_checksum: `sha256:${"a".repeat(64)}`,
      source_geometry_ref: sourceGeometry,
      target_rgb_geometry_ref: targetGeometry,
      candidates: [{
        candidate_id: "candidate-1",
        rgb_scale_factor: 1.25,
        transform_target_from_source: candidateTransform,
      }],
    };
    const preview = {
      schema_version: "1.0",
      artifact_type: "RegistrationOverlayPreview",
      producer_stage: "RGB_LIDAR_ALIGN",
      job_id: "job-1",
      operation_id: request.request_id,
      input_mode: "static_cloud",
      request_checksum: request.request_checksum,
      source_input_checksum: `sha256:${"b".repeat(64)}`,
      source_geometry_ref: sourceGeometry,
      target_rgb_geometry_ref: targetGeometry,
      target_scene_revision: "rev-001",
      request_target_roi_world: { min_xyz_m: [-20, -20, -2], max_xyz_m: [20, 20, 8] },
      target_floor_evidence_checksum: `sha256:${"8".repeat(64)}`,
      profile_checksum: `sha256:${"a".repeat(64)}`,
      candidate_id: "candidate-1",
      source_frame: "lidar-map",
      transform_target_from_source: candidateTransform,
      rgb_scale_factor: 1.25,
      bounds_min_xy_m: [-20, -20],
      bounds_max_xy_m: [20, 20],
      source_in_roi_point_count: 1,
      target_in_roi_point_count: 1,
      source_points_xy_world_m: [[1, 2]],
      target_points_xy_world_m: [[3, 4]],
      sample_cap_per_cloud: 512,
      sampling_method: "uniform_order_indices_v1",
      diagnostic_only: true,
      preview_checksum: `sha256:${"9".repeat(64)}`,
    };
    const inspection = {
      operation_id: request.request_id,
      job_id: "job-1",
      expected_scene_revision: "rev-001",
      current_scene_revision: "rev-001",
      proposal,
      qa_report: {
        schema_version: "1.0",
        artifact_type: "RegistrationQAReport",
        job_id: "job-1",
        target_scene_revision: "rev-001",
        proposal_checksum: proposalChecksum,
        report_checksum: `sha256:${"d".repeat(64)}`,
      },
      overlay_previews: [preview],
    };

    expect(parseRegistrationOperationInspection(inspection, "job-1", request.request_id).overlay_previews)
      .toHaveLength(1);
    expect(() => parseRegistrationOperationInspection({
      ...inspection,
      overlay_previews: [{ ...preview, operation_id: "another-operation" }],
    }, "job-1", request.request_id)).toThrow(/operation, job/);
    expect(() => parseRegistrationOperationInspection({
      ...inspection,
      overlay_previews: [{ ...preview, source_points_xy_world_m: [[21, 2]] }],
    }, "job-1", request.request_id)).toThrow(/operation, job/);
    expect(() => parseRegistrationOperationInspection({
      ...inspection,
      overlay_previews: [preview, preview],
    }, "job-1", request.request_id)).toThrow(/operation, job/);
    expect(() => parseRegistrationOperationInspection({
      ...inspection,
      qa_report: null,
    }, "job-1", request.request_id)).toThrow(/operation, job/);
  });

  it("keeps watching proposal and review states but stops at terminal states", () => {
    expect(isRegistrationOperationPollable("PROPOSED")).toBe(true);
    expect(isRegistrationOperationPollable("AMBIGUOUS")).toBe(true);
    expect(isRegistrationOperationPollable("REVIEWED")).toBe(true);
    expect(isRegistrationOperationPollable("CONFIRMED")).toBe(true);
    expect(isRegistrationOperationPollable("INSUFFICIENT")).toBe(false);
    expect(isRegistrationOperationPollable("FAILED")).toBe(false);
    expect(isRegistrationOperationPollable("COMMITTED")).toBe(false);
    expect(isRegistrationOperationPollable("CANCELLED")).toBe(false);
  });

  it("offers cancellation only for queued, running or resource-waiting work", () => {
    expect(isRegistrationOperationActive("REQUESTED")).toBe(false);
    expect(isRegistrationOperationActive("QUEUED")).toBe(true);
    expect(isRegistrationOperationActive("RUNNING")).toBe(true);
    expect(isRegistrationOperationActive("WAITING_RESOURCES")).toBe(true);
    expect(isRegistrationOperationActive("PROPOSED")).toBe(false);
  });

  it("uses the sealed request ID as the idempotency key", async () => {
    const response = {
      operation_id: request.request_id,
      job_id: "job-1",
      state: "QUEUED",
      attempt: 0,
      created_at: "2026-10-09T00:00:00Z",
      updated_at: "2026-10-09T00:00:00Z",
      proposal_ref: null,
      qa_report_ref: null,
      cancellation_requested: false,
    };
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), { status: 202 }));

    await enqueueRegistration("job-1", request);

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/jobs/job-1/rgb-lidar-registration/operations",
      expect.objectContaining({ headers: expect.objectContaining({ "Idempotency-Key": request.request_id }) }),
    );
  });

  it("sends confirmation with the optimistic operation and scene revisions", async () => {
    const response = {
      operation_id: request.request_id,
      job_id: "job-1",
      state: "CONFIRMED",
      operation_checksum: `sha256:${"b".repeat(64)}`,
      attempt: 1,
      created_at: "2026-10-09T00:00:00Z",
      updated_at: "2026-10-09T00:01:00Z",
      proposal_ref: null,
      qa_report_ref: null,
      cancellation_requested: false,
      confirmed_candidate_id: "candidate-1",
      confirmed_by_user_id: "user-1",
      confirmed_at: "2026-10-09T00:01:00Z",
    };
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }));

    const confirmed = await confirmRegistrationOperation("job-1", request.request_id, {
      expected_operation_checksum: `sha256:${"a".repeat(64)}`,
      expected_scene_revision: "rev-001",
      candidate_id: "candidate-1",
    });

    expect(confirmed.state).toBe("CONFIRMED");
    expect(fetch).toHaveBeenCalledWith(
      `/api/v1/jobs/job-1/rgb-lidar-registration/operations/${request.request_id}/confirm`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expected_operation_checksum: `sha256:${"a".repeat(64)}`,
          expected_scene_revision: "rev-001",
          candidate_id: "candidate-1",
        }),
      }),
    );
  });
});
