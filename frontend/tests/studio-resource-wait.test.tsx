/** Queue animation/API parsing fixture proof, không thay real worker/browser E2E. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProgressTab } from "@/features/studio/scene/ProgressTab";
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
    render(<ProgressTab jobId={progress.job_id} progress={progress} info={null} busy={false} onCancel={cancel} />);
    expect(screen.getByText(/Đang chờ đủ tài nguyên/)).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Đang chờ trong hàng đợi" });
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar.querySelector(".studio-indeterminate")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Huỷ xử lý" }));
    expect(cancel).toHaveBeenCalledOnce();
    expect(progressSceneStatus(progress).label).toBe("Đang chờ tài nguyên");
  });
  it("parse snapshot backend và từ chối nguồn số đo lỗi", () => {
    expect(parseJobProgress(progress).waiting_for).toBe("resources");
    expect(() => parseJobProgress({ ...progress, waiting_for: "invented" })).toThrow();
    expect(() => parseJobProgress({ ...progress, resource_wait: { ...progress.resource_wait,
      required_gb: { vram: "six", ram: 8, disk: 10 } } })).toThrow();
  });
});
