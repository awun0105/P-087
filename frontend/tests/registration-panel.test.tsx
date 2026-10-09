import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegistrationPanel } from "@/features/studio/scene/RegistrationPanel";
import { ApiError } from "@/lib/api/client";
import type { Me } from "@/lib/api/auth";
import {
  cancelRegistrationOperation,
  enqueueRegistration,
  getRegistrationOperation,
  prepareRegistration,
  type RegistrationOperation,
  type RegistrationPreparation,
  type RegistrationRequestPayload,
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
    enqueueRegistration: vi.fn(),
    getRegistrationOperation: vi.fn(),
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
    attempt: 1,
    created_at: "2026-10-09T00:00:00Z",
    updated_at: "2026-10-09T00:00:00Z",
    proposal_ref: null,
    qa_report_ref: null,
    cancellation_requested: false,
    ...updates,
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
      .mockResolvedValueOnce({ ok: true, data: operation("PROPOSED", { proposal_ref: { artifact_type: "RegistrationProposal" }, qa_report_ref: { artifact_type: "RegistrationQAReport" } }) })
      .mockResolvedValue({ ok: true, data: operation("REVIEWED") });

    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));
    expect(await screen.findByText(/đạt preflight/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu căn chỉnh" }));

    await screen.findByText("Có đề xuất cần kiểm tra");
    expect(prepareRegistration).toHaveBeenCalledWith("job-1", "rev-001");
    expect(enqueueRegistration).toHaveBeenCalledWith("job-1", request);
    expect(screen.getByText(/chưa có transform nào được áp dụng/i)).toBeInTheDocument();
    expect(window.sessionStorage.getItem("real2sim:rgb-lidar-registration:v1:guest-1:job-1")).toContain(request.request_id);
    await screen.findByText("Đã kiểm tra", {}, { timeout: 5000 });
    expect(getRegistrationOperation).toHaveBeenCalledTimes(2);
  });

  it("does not enqueue when the server reports insufficient preflight", async () => {
    vi.mocked(prepareRegistration).mockResolvedValue({
      request,
      preflight: { request_checksum: request.request_checksum, state: "INSUFFICIENT", findings: ["FLOOR_UNCERTAIN"] },
    });

    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob />);
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra dữ liệu" }));

    expect(await screen.findByText("Chưa thể chạy registration.")).toBeInTheDocument();
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
    await screen.findByText(/đạt preflight/);
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
    expect(screen.getByText(/revision rev-001.*revision hiện tại là rev-002/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bắt đầu căn chỉnh" })).not.toBeInTheDocument();
    expect(enqueueRegistration).not.toHaveBeenCalled();
  });

  it("keeps read-only users from starting or cancelling registration", () => {
    render(<RegistrationPanel jobId="job-1" sceneRevision="rev-001" canMutateJob={false} />);
    expect(screen.getByText(/chế độ chỉ xem/)).toBeInTheDocument();
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
    expect(screen.getByText(/Worker sẽ dừng an toàn/)).toBeInTheDocument();
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
});
