/** T-065: bước Frames và Cameras không nạp module 3D (three/r3f/PlayCanvas); lớp 3DGS mới nạp. */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StageViewer } from "@/features/studio/StageViewer";
import { getStageViews } from "@/lib/api/studio";
import type { StageView } from "@/lib/contracts/studio";

const loaded = vi.hoisted(() => ({ value: false }));
vi.mock("@/lib/api/studio", () => ({ getStageViews: vi.fn() }));
vi.mock("@/features/studio/StageViewer3D", () => {
  loaded.value = true;
  return { Stage3DLayer: () => <div>3D layer</div> };
});

const cameras: StageView = { stage_id: "ST-CAMERA-POSE", kind: "cameras", title: "Camera", note: "", unit: "arbitrary", refs: [], cameras: [{ frame_id: 0, center: [0, 0, 0], rotation_xyzw: [0, 0, 0, 1] }] };
const gaussian: StageView = { stage_id: "ST-VISUAL-RECON", kind: "gaussian", title: "Gaussian", note: "", unit: "arbitrary", refs: [{ artifact_type: "GaussianSOG", artifact_uri: "artifact://jobs/job-a/scene.sog", artifact_checksum: `sha256:${"a".repeat(64)}` }], cameras: [] };

beforeEach(() => vi.mocked(getStageViews).mockResolvedValue([cameras, gaussian]));

describe("stage viewer bundles split by layer (T-065)", () => {
  it("frames and cameras views do not import the 3D module", async () => {
    render(<StageViewer jobId="job-a" stageId="ST-CAMERA-POSE" />);
    expect(await screen.findByRole("img", { name: "Quỹ đạo camera nhìn từ trên xuống" })).toBeInTheDocument();
    expect(loaded.value).toBe(false);
  });

  it("a gaussian view loads the 3D module", async () => {
    render(<StageViewer jobId="job-a" stageId="ST-VISUAL-RECON" />);
    expect(await screen.findByText("3D layer")).toBeInTheDocument();
    expect(loaded.value).toBe(true);
  });
});
