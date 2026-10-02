/** Component fixture proof cho mẫu tại bước upload, không phải 3DGS/GPU acceptance. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SampleProcessStep } from "@/features/studio/SampleFlow";
import { MVP_STAGES } from "@/features/studio/stages";
import type { DemoManifest } from "@/lib/contracts/studio";

vi.mock("@/features/studio/DemoShowcase", () => ({ DemoShowcase: () => <div>Output của mẫu</div> }));

const sample: DemoManifest = {
  schema_version: "1.0", demo_id: "old", title: "Mẫu cũ", description: "", origin: "pipeline_job",
  source: { dataset: "TorWIC-SLAM", sequence: "Aisle_CW", note: "" }, produced_at: "2026-10-02T00:00:00Z",
  provenance: {}, frames: [], frame_count: 5, video: null, processing: null, machine: {},
  splat: { name: "scene.sog", media_type: "application/octet-stream", size_bytes: 10, checksum: "sha256:test" },
  stages: MVP_STAGES.map((meta) => ({ stage_id: meta.id, duration_seconds: 1, summary: "" })),
};

describe("mẫu cũ tại bước upload", () => {
  it("hiện pipeline 8 bước, bỏ qua chỉ hoàn tất 5 bước đã ghi", () => {
    const onDone = vi.fn();
    render(<SampleProcessStep sampleId="old" sample={sample} onDone={onDone} />);
    expect(screen.getByText("Xác nhận tỉ lệ mét")).toBeInTheDocument();
    expect(screen.getByText("Hình học & collision")).toBeInTheDocument();
    expect(screen.getByText("Tách vật thể")).toBeInTheDocument();
    expect(screen.getByText(/Mẫu cũ chưa ghi kết quả/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bỏ qua" }));
    expect(screen.getByText("5/8 bước hoàn tất")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mở scene 3D/ })).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
  });
});
