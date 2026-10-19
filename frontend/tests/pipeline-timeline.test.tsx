import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PipelineTimeline, type StageView } from "@/features/studio/PipelineTimeline";
import type { ExecutionError, StageId } from "@/lib/contracts/api";
import { parseJobProgress } from "@/lib/contracts/studio";

function stageWithError(error: ExecutionError, stageId: StageId = "ST-CAMERA-POSE"): StageView[] {
  return [
    {
      stage_id: stageId,
      state: "failed",
      seconds: 12,
      fraction: null,
      error,
    },
  ];
}

describe("PipelineTimeline error guidance rendering", () => {
  it("hiển thị ETA chưa xác định cho job chạy khi không có số đo hỗ trợ", () => {
    render(
      <PipelineTimeline
        jobId="job-running"
        stages={[{ stage_id: "ST-VISUAL-RECON", state: "running", seconds: 900, fraction: null }]}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Thời gian còn lại chưa xác định");
    expect(screen.queryByText(/Còn ~\d/)).not.toBeInTheDocument();
  });

  it("không gắn ETA của job vào replay demo", () => {
    render(
      <PipelineTimeline
        stages={[{ stage_id: "ST-VISUAL-RECON", state: "running", seconds: null, fraction: 0.5 }]}
      />,
    );

    expect(screen.queryByText("Thời gian còn lại chưa xác định")).not.toBeInTheDocument();
    expect(screen.queryByText(/Còn ~\d/)).not.toBeInTheDocument();
  });

  it("hiển thị cause và fix cho mã lỗi đã có guidance", () => {
    const error: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "COLMAP_OUT_OF_MEMORY",
      human_message: "COLMAP process ran out of memory",
      retryable: true,
      details: {},
    };

    render(<PipelineTimeline stages={stageWithError(error)} />);

    expect(screen.getByText(/Máy xử lý hết RAM khi dựng vị trí camera\./)).toBeInTheDocument();
    expect(
      screen.getByText(/Giảm "Số khung hình tối đa" hoặc "Số điểm đặc trưng mỗi ảnh" rồi chạy lại\./),
    ).toBeInTheDocument();
    expect(screen.getByText("(COLMAP_OUT_OF_MEMORY)")).toBeInTheDocument();
    expect(screen.getByText("Có thể thử lại")).toBeInTheDocument();
  });

  it("hiển thị human_message khi gặp mã lỗi lạ chưa có guidance", () => {
    const error: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "UNKNOWN_PROCESS_FAILURE",
      human_message: "Lỗi tiến trình không xác định",
      retryable: false,
      details: null,
    };

    render(<PipelineTimeline stages={stageWithError(error)} />);

    expect(screen.getByText(/Lỗi tiến trình không xác định/)).toBeInTheDocument();
    expect(screen.getByText("(UNKNOWN_PROCESS_FAILURE)")).toBeInTheDocument();
    expect(screen.getByText("Cần sửa đầu vào trước khi chạy lại")).toBeInTheDocument();
  });

  it("hiển thị nhãn thử lại đúng theo cờ retryable", () => {
    const retryableErr: ExecutionError = {
      stage_id: "ST-VISUAL-RECON",
      error_code: "VISUAL_OUT_OF_MEMORY",
      human_message: "GPU out of memory",
      retryable: true,
    };
    const { unmount } = render(<PipelineTimeline stages={stageWithError(retryableErr, "ST-VISUAL-RECON")} />);
    expect(screen.getByText("Có thể thử lại")).toBeInTheDocument();
    unmount();

    const nonRetryableErr: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "COLMAP_NO_MODEL",
      human_message: "No model produced",
      retryable: false,
    };
    render(<PipelineTimeline stages={stageWithError(nonRetryableErr)} />);
    expect(screen.getByText("Cần sửa đầu vào trước khi chạy lại")).toBeInTheDocument();
  });

  it("render 'Chi tiết kỹ thuật' khi có log_excerpt và ẩn khi không có", () => {
    const withLog: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "COLMAP_PROCESS_FAILED",
      human_message: "COLMAP exited with code 1",
      retryable: false,
      details: {
        log_excerpt: ["line 1 of error", "line 2 of error"],
      },
    };

    const { unmount } = render(<PipelineTimeline stages={stageWithError(withLog)} />);
    expect(screen.getByText("Chi tiết kỹ thuật")).toBeInTheDocument();
    expect(screen.getByText(/line 1 of error/)).toBeInTheDocument();
    unmount();

    const withoutLog: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "COLMAP_PROCESS_FAILED",
      human_message: "COLMAP exited with code 1",
      retryable: false,
      details: {},
    };

    render(<PipelineTimeline stages={stageWithError(withoutLog)} />);
    expect(screen.queryByText("Chi tiết kỹ thuật")).not.toBeInTheDocument();
  });

  it("chọn đúng một trong hai hướng khắc phục của COLMAP_NO_MODEL theo diagnostics", () => {
    const noInitialPairErr: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "COLMAP_NO_MODEL",
      human_message: "COLMAP produced no sparse model",
      retryable: false,
      details: {
        diagnostics: { no_initial_pair: 2, insufficient_size: 0 },
      },
    };

    const { unmount } = render(<PipelineTimeline stages={stageWithError(noInitialPairErr)} />);
    expect(
      screen.getByText(/Các khung hình liên tiếp không có đủ điểm chung\. Quay chậm hơn, giữ vật thể trong khung và tránh bề mặt trơn một màu\./),
    ).toBeInTheDocument();
    unmount();

    const disconnectedErr: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "COLMAP_NO_MODEL",
      human_message: "COLMAP produced no sparse model",
      retryable: false,
      details: {
        diagnostics: { no_initial_pair: 0, insufficient_size: 3 },
      },
    };

    render(<PipelineTimeline stages={stageWithError(disconnectedErr)} />);
    expect(
      screen.getByText(/Cảnh bị tách thành nhiều đoạn rời\. Quay một vòng liền mạch, không cắt ngang\./),
    ).toBeInTheDocument();
  });

  it("hiển thị số liệu COLMAP_REGISTRATION_LOW có kiểm tra kiểu", () => {
    const error: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "COLMAP_REGISTRATION_LOW",
      human_message: "Best COLMAP model is below configured registration threshold",
      retryable: false,
      details: { registered_frames: 33, input_frames: 100, min_registered_ratio: 0.5 },
    };

    render(<PipelineTimeline stages={stageWithError(error)} />);

    expect(screen.getByText("Chỉ dựng được vị trí cho 33/100 ảnh, dưới ngưỡng 50%.")).toBeInTheDocument();
    expect(screen.getByText(/Quay chậm hơn và để các khung hình liên tiếp chồng lấn nhiều hơn\./)).toBeInTheDocument();
  });

  it("giữ retryable và details khi parse job progress", () => {
    const error: ExecutionError = {
      stage_id: "ST-CAMERA-POSE",
      error_code: "COLMAP_NO_MODEL",
      human_message: "COLMAP produced no sparse model",
      retryable: false,
      details: { diagnostics: { no_initial_pair: 2 }, log_excerpt: ["line 1"] },
    };
    const parsed = parseJobProgress({
      job_id: "job-a",
      status: "FAILED",
      current_stage: "ST-CAMERA-POSE",
      attempt: 1,
      started_at: "2026-10-01T00:00:00Z",
      updated_at: "2026-10-01T00:01:00Z",
      completed_at: "2026-10-01T00:01:00Z",
      stages: [{ stage_id: "ST-CAMERA-POSE", state: "failed", started_at: null, completed_at: null, error }],
      preview_ready: false,
      error,
    });

    expect(parsed.stages[0].error?.retryable).toBe(false);
    expect(parsed.stages[0].error?.details).toEqual(error.details);
    expect(parsed.error?.details).toEqual(error.details);
  });
});
