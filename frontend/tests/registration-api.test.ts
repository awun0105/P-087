import { afterEach, describe, expect, it, vi } from "vitest";

import {
  enqueueRegistration,
  isRegistrationOperationActive,
  isRegistrationOperationPollable,
  parseRegistrationOperation,
  parseRegistrationPreparation,
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
});
