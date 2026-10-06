/** Proof điều phối workspace; renderer được mock, không thay bằng GPU acceptance. */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Link from "next/link";

import { StageSceneWorkspace } from "@/features/studio/inspection/StageSceneWorkspace";
import { ApiError } from "@/lib/api/client";
import { getPreview } from "@/lib/api/endpoints";
import type { ProductArtifactRef } from "@/lib/contracts/api";
import type { ReconstructionPreview } from "@/lib/contracts/preview";

vi.mock("@/lib/api/endpoints", async (original) => ({ ...(await original<typeof import("@/lib/api/endpoints")>()), getPreview: vi.fn() }));
vi.mock("@/features/studio/scene/PreviewScene", () => ({ PreviewScene: ({ contentUrl, title }: { contentUrl: string; title: string }) => <div aria-label={title}><Link href="/scenes/job-a?tab=progress">Về tiến trình editor</Link><output>{contentUrl}</output></div> }));
vi.mock("@/features/studio/StageViewer", () => ({ StageViewer: ({ stageId, fallbackStageId }: { stageId: string; fallbackStageId?: string }) => <div>Viewer: {stageId}<span>Fallback: {fallbackStageId ?? "none"}</span></div> }));
vi.mock("@/features/studio/ObjectReviewView", () => ({ ObjectReviewView: ({ jobId }: { jobId: string }) => <div>Objects: {jobId}</div> }));
vi.mock("@/features/studio/ModeComparisonView", () => ({ ModeComparisonView: ({ jobId }: { jobId: string }) => <div>Comparison: {jobId}</div> }));

const sha = `sha256:${"a".repeat(64)}`;
function ref(artifact_type: string, name: string, producer_stage: string): ProductArtifactRef {
  return { schema_version: "1.0", job_id: "job-a", artifact_type, artifact_uri: `artifact://jobs/job-a/attempts/a1/${name}`, artifact_checksum: sha, data_class: "derived", producer_stage };
}
const preview: ReconstructionPreview = {
  schema_version: "1.0", artifact_type: "ReconstructionPreview", job_id: "job-a", attempt_id: "a1", source_input_checksum: sha,
  source_visual_ref: ref("BrushVisualArtifact", "visual.json", "ST-VISUAL-RECON"), camera_pose_ref: ref("CameraPoseArtifact", "cameras.json", "ST-CAMERA-POSE"), delivery_ref: ref("GaussianSOG", "scene.sog", "ST-VISUAL-RECON"),
  format: "gaussian_sog", producer: "brush", producer_version: "fixture", metric_status: "UNCONFIRMED", coordinate_frame: "sfm_world", unit: "arbitrary",
};
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getPreview).mockResolvedValue({ ok: true, data: preview }); });

describe("workspace scene 5–8", () => {
  it("5 dùng editor hiện có với ref đã publish và quay về đúng tiến trình", async () => {
    render(<StageSceneWorkspace jobId="job-a" stageId="ST-VISUAL-RECON" title="Kho A" />);
    const editor = await screen.findByLabelText("5. 3DGS: Kho A");
    expect(editor).toHaveTextContent("/api/v1/jobs/job-a/artifacts/content/scene.sog");
    expect(editor).toHaveTextContent("artifact_checksum=sha256%3A");
    expect(screen.getByRole("link", { name: "Về tiến trình editor" })).toHaveAttribute("href", "/scenes/job-a?tab=progress");
    expect(screen.getByText(/chưa quy đổi mét/)).toBeInTheDocument();
  });

  it("5 lỗi preview không mount editor, có thể thử lại", async () => {
    vi.mocked(getPreview).mockResolvedValueOnce({ ok: false, error: new ApiError(503, "Preview tạm thời không có") });
    render(<StageSceneWorkspace jobId="job-a" stageId="ST-VISUAL-RECON" title="Kho A" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Máy chủ chưa xử lý được yêu cầu");
    expect(screen.queryByLabelText("5. 3DGS: Kho A")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByLabelText("5. 3DGS: Kho A")).toBeInTheDocument();
  });

  it("6 xem scene hoặc so sánh đã publish, không mở lại công cụ xác nhận", async () => {
    render(<StageSceneWorkspace jobId="job-a" stageId="ST-METRIC-CANONICALIZE" title="Kho A" />);
    expect(await screen.findByText("Viewer: ST-METRIC-CANONICALIZE")).toBeInTheDocument();
    expect(screen.getByText("Fallback: ST-VISUAL-RECON")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Xem số đo & so sánh" }));
    expect(await screen.findByText("Comparison: job-a")).toBeInTheDocument();
    expect(screen.queryByText("Viewer: ST-METRIC-CANONICALIZE")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Scene 3D" }));
    expect(await screen.findByText("Viewer: ST-METRIC-CANONICALIZE")).toBeInTheDocument();
    expect(getPreview).not.toHaveBeenCalled();
  });

  it("7 dùng collision view riêng, không thay bằng Gaussian gốc", async () => {
    render(<StageSceneWorkspace jobId="job-a" stageId="ST-RGB-GEOMETRY" title="Kho A" />);
    expect(await screen.findByText("Viewer: ST-RGB-GEOMETRY")).toBeInTheDocument();
    expect(screen.getByText("Fallback: none")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Công cụ hệ mét" })).toBeNull();
  });

  it("8 tái sử dụng công cụ SceneObject hiện tại và nói rõ tạo revision mới", async () => {
    render(<StageSceneWorkspace jobId="job-a" stageId="ST-OBJECT-EXTRACT" title="Kho A" />);
    expect(await screen.findByText("Objects: job-a")).toBeInTheDocument();
    expect(screen.getByText(/SceneObject hiện tại.*revision mới/)).toBeInTheDocument();
    expect(getPreview).not.toHaveBeenCalled();
  });
});
