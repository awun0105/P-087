/** Queue animation/API parsing fixture proof, không thay real worker/browser E2E. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProgressTab } from "@/features/studio/scene/ProgressTab";
import { roughDuration } from "@/features/studio/scene/QueueStatus";
import { progressSceneStatus } from "@/features/studio/sceneStatus";
import { parseJobProgress, type JobProgress } from "@/lib/contracts/studio";

vi.mock("@/features/studio/scene/AttemptHistory", () => ({ AttemptHistory: () => <div /> }));

const progress: JobProgress = {
  job_id: "job-queued", status: "QUEUED", current_stage: "ST-INPUT-VALIDATE", attempt: 1,
  started_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:05Z", completed_at: null,
  preview_ready: false, error: null, waiting_for: "resources", stages: [],
  resource_wait: { job_manifest_checksum: "sha256:test", checked_at: "2026-10-02T00:00:05Z",
    required_gb: { vram: 6, ram: 8, disk: 10 }, available_gb: { vram: 3, ram: 16, disk: 20 },
    waiting_on: ["vram"], estimate_scope: "configured_preview" },
};

describe("đợi tài nguyên với config đã chọn", () => {
  it("animation chờ không bịa phần trăm, vẫn cho huỷ", () => {
    const cancel = vi.fn();
    render(<ProgressTab jobId={progress.job_id} progress={progress} info={null} busy={false} canCancel onCancel={cancel} />);
    expect(screen.getByText(/Đang chờ máy xử lý đủ tài nguyên/)).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Đang chờ trong hàng đợi" });
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar.querySelector(".studio-indeterminate")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Huỷ xử lý" }));
    expect(cancel).toHaveBeenCalledOnce();
    expect(progressSceneStatus(progress).label).toBe("Đang chờ tài nguyên");
  });
  it("nói rõ thiếu gì, bao nhiêu và việc chờ có tự hết không", () => {
    const wait = { ...progress.resource_wait!, waiting_on: ["vram", "disk"] as ("vram" | "disk")[],
      available_gb: { vram: 3, ram: 16, disk: null }, reasons: { vram: "busy" as const, disk: "unmeasured" as const },
      capacity_gb: { vram: 8, ram: 32, disk: null } };
    const { rerender } = render(<ProgressTab jobId={progress.job_id} progress={{ ...progress, resource_wait: wait }} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText(/VRAM GPU: cần khoảng 6\.0 GB, đang có 3\.0 GB \(máy có tổng 8\.0 GB\)/)).toBeInTheDocument();
    expect(screen.getByText(/Việc khác đang dùng phần này/)).toBeInTheDocument();
    expect(screen.getByText(/Ổ đĩa: cần khoảng 10\.0 GB, đang có chưa đo được/)).toBeInTheDocument();
    expect(screen.queryByText(/RAM: cần/)).not.toBeInTheDocument();
    rerender(<ProgressTab jobId={progress.job_id} progress={{ ...progress, resource_wait: { ...wait, waiting_on: ["vram"], reasons: { vram: "exceeds_machine" } } }} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText(/vượt sức máy xử lý nên sẽ không chạy/)).toBeInTheDocument();
    // Chưa có số đo: nói rõ job chờ để chạy một mình, không trình bày con số VRAM như thứ đang thiếu.
    rerender(<ProgressTab jobId={progress.job_id} progress={{ ...progress, resource_wait: { ...wait, waiting_on: ["vram"], reasons: { vram: "busy" }, needs_exclusive_gpu: true } }} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText(/đang chờ được chạy một mình/)).toBeInTheDocument();
    expect(screen.queryByText(/VRAM GPU: cần/)).not.toBeInTheDocument();
    // Có số đo: ghi rõ con số là mức các lượt trước đã dùng.
    rerender(<ProgressTab jobId={progress.job_id} progress={{ ...progress, resource_wait: { ...wait, waiting_on: ["vram"], reasons: { vram: "busy" }, estimate_scope: "measured" } }} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText(/VRAM GPU: các lượt chạy trước đã dùng tới 6\.0 GB, đang có 3\.0 GB/)).toBeInTheDocument();
    // Cận trên: số đo lấy từ cấu hình nặng hơn, không trình bày như số đo của đúng cấu hình này.
    rerender(<ProgressTab jobId={progress.job_id} progress={{ ...progress, resource_wait: { ...wait, waiting_on: ["vram"], reasons: { vram: "busy" }, estimate_scope: "upper_bound" } }} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText(/VRAM GPU: theo số đo của cấu hình nặng hơn, cần tối đa 6\.0 GB, đang có 3\.0 GB/)).toBeInTheDocument();
    // Observation của worker cũ (không có lý do) vẫn hiện số đo.
    rerender(<ProgressTab jobId={progress.job_id} progress={progress} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText(/VRAM GPU: cần khoảng 6\.0 GB, đang có 3\.0 GB/)).toBeInTheDocument();
  });
  it("hiện vị trí hàng đợi và thời gian chờ chỉ khi có số đo", () => {
    const queue = { position: 3, waiting: 4, running: 1, workers: 1, estimated_wait_seconds: 1500, estimate_samples: 6 };
    const { rerender } = render(<ProgressTab jobId={progress.job_id} progress={{ ...progress, waiting_for: null, resource_wait: null, queue }} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText(/Trước bạn còn 2 việc đang chờ\. 1 việc đang chạy trên 1 máy xử lý\./)).toBeInTheDocument();
    expect(screen.getByText(/Dự kiến chờ khoảng 25 phút\./)).toBeInTheDocument();
    expect(screen.getByText(/Mỗi người một lượt/)).toBeInTheDocument();
    rerender(<ProgressTab jobId={progress.job_id} progress={{ ...progress, waiting_for: null, resource_wait: null, queue: { ...queue, position: 1, waiting: 1, running: 0, estimated_wait_seconds: null, estimate_samples: 0 } }} info={null} busy={false} canCancel={false} onCancel={vi.fn()} />);
    expect(screen.getByText(/Scene của bạn là việc kế tiếp\./)).toBeInTheDocument();
    expect(screen.getByText(/Chưa ước tính được thời gian chờ/)).toBeInTheDocument();
    expect(screen.queryByText(/khoảng \d+ phút/)).not.toBeInTheDocument(); // không có số đo thì không điền số
    expect(roughDuration(20)).toBe("khoảng 1 phút");
    expect(roughDuration(3900)).toBe("khoảng 1 giờ 5 phút");
    expect(roughDuration(7200)).toBe("khoảng 2 giờ");
    expect(parseJobProgress({ ...progress, queue }).queue?.position).toBe(3);
    expect(() => parseJobProgress({ ...progress, queue: { ...queue, position: 0 } })).toThrow();
    expect(() => parseJobProgress({ ...progress, queue: { ...queue, estimated_wait_seconds: -5 } })).toThrow();
    expect(() => parseJobProgress({ ...progress, queue: { ...queue, workers: "many" } })).toThrow();
  });
  it("parse snapshot backend và từ chối nguồn số đo lỗi", () => {
    expect(() => parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait, reasons: { vram: "invented" } } })).toThrow();
    expect(() => parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait, estimate_scope: "guessed" } })).toThrow();
    expect(() => parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait, needs_exclusive_gpu: "yes" } })).toThrow();
    expect(parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait, estimate_scope: "measured", needs_exclusive_gpu: false } }).resource_wait?.estimate_scope).toBe("measured");
    expect(parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait, estimate_scope: "upper_bound" } }).resource_wait?.estimate_scope).toBe("upper_bound");
    expect(() => parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait, capacity_gb: { vram: "big" } } })).toThrow();
    expect(parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait, reasons: { vram: "external" }, capacity_gb: { vram: 4, ram: 31, disk: null } } }).resource_wait?.reasons?.vram).toBe("external");
    expect(parseJobProgress(progress).waiting_for).toBe("resources");
    expect(() => parseJobProgress({ ...progress, waiting_for: "invented" })).toThrow();
    expect(() => parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait,
      required_gb: { vram: "six", ram: 8, disk: 10 } } })).toThrow();
  });
});
