import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResourceWaitDetail } from "@/features/studio/scene/ResourceWaitDetail";
import { parseJobProgress } from "@/lib/contracts/studio";

const wait = {
  job_manifest_checksum: "sha256:" + "a".repeat(64),
  checked_at: "2026-10-20T08:00:00Z",
  required_gb: { vram: 4, ram: 8, disk: 2 },
  available_gb: { vram: null, ram: null, disk: null },
  waiting_on: ["vram"],
  estimate_scope: "configured_preview",
  reasons: { vram: "gate_error" },
  capacity_gb: { vram: null },
  needs_exclusive_gpu: false,
};

describe("gate_error resource wait (T-050)", () => {
  it("is accepted by the progress parser", () => {
    const progress = {
      job_id: "job-a", status: "QUEUED", current_stage: "ST-INPUT-VALIDATE", attempt: 1,
      started_at: "2026-10-20T08:00:00Z", updated_at: "2026-10-20T08:00:00Z", completed_at: null,
      stages: [], preview_ready: false, waiting_for: "resources", resource_wait: wait, queue: null, error: null,
    };
    expect(parseJobProgress(progress).resource_wait?.reasons?.vram).toBe("gate_error");
  });

  it("explains that the resource check itself failed", () => {
    render(<ResourceWaitDetail wait={wait as never} />);
    expect(screen.getByText(/kiểm tra tài nguyên bị lỗi/)).toBeTruthy();
  });
});
