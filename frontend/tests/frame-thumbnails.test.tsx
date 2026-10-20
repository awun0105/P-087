/** T-066: lưới frame dùng ảnh thu nhỏ; bấm một ảnh mới tải ảnh gốc. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StageViewer } from "@/features/studio/StageViewer";
import { getStageViews } from "@/lib/api/studio";
import type { StageView } from "@/lib/contracts/studio";

vi.mock("@/lib/api/studio", () => ({ getStageViews: vi.fn() }));
vi.mock("@/features/studio/StageViewer3D", () => ({ Stage3DLayer: () => <div /> }));

const frames: StageView = {
  stage_id: "ST-FRAME-EXTRACT", kind: "frames", title: "Frame", note: "", unit: "arbitrary", cameras: [],
  refs: [1, 2].map((n) => ({ artifact_type: "Frame", artifact_uri: `artifact://jobs/job-a/frames/frame_000${n}.png`, artifact_checksum: `sha256:${String(n).repeat(64)}` })),
};

describe("frame grid thumbnails (T-066)", () => {
  it("shows thumbnails and opens the original on click", async () => {
    vi.mocked(getStageViews).mockResolvedValue([frames]);
    render(<StageViewer jobId="job-a" stageId="ST-FRAME-EXTRACT" />);
    const image = await screen.findByRole("img", { name: "frame_0001.png" });
    expect(image.getAttribute("src")).toContain("/frames/thumbnail");
    expect(image.getAttribute("src")).toContain("width=320");
    expect(image.getAttribute("srcset")).toContain("width=640");
    expect(image.getAttribute("src")).not.toContain("/artifacts/content");

    fireEvent.click(screen.getByRole("button", { name: "Xem ảnh gốc frame_0001.png" }));
    const original = screen.getByRole("img", { name: "Ảnh gốc frame_0001.png" });
    expect(original.getAttribute("src")).toContain("/artifacts/content");
    fireEvent.click(screen.getByRole("button", { name: "Đóng ảnh gốc" }));
    expect(screen.queryByRole("img", { name: "Ảnh gốc frame_0001.png" })).toBeNull();
  });
});
