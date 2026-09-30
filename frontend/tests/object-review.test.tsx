/**
 * ObjectReviewView (ADR 0006, PRODUCT-07): xác nhận/loại ứng viên gửi đúng revision, UI hiển
 * thị revision backend trả về. Canvas 3D được thay bằng stub (jsdom không có WebGL).
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectReviewView } from "@/features/studio/ObjectReviewView";

vi.mock("@/features/studio/StageViewer", () => ({
  CollisionMeshCanvas: () => <div data-testid="mesh" />,
}));

const ref = {
  artifact_type: "SceneObjectGeometry",
  schema_version: "1.0",
  artifact_uri: "artifact://jobs/job-a/scene/candidates/x.glb",
  artifact_checksum: "sha256:" + "a".repeat(64),
  data_class: "derived",
  producer_stage: "ST-OBJECT-ASSOC",
  job_id: "job-a",
};

function scene(revision: string, state: "CANDIDATE" | "CONFIRMED", review?: string) {
  return {
    scene_revision: revision,
    environment: { geometry_ref: { ...ref, artifact_uri: "artifact://jobs/job-a/rec05/collision.glb" } },
    provenance: { object_extraction: "sampro3d_sam2_v1" },
    objects: [
      {
        id: "candidate-001",
        name: "Vật thể 1",
        state,
        active: state === "CONFIRMED",
        origin: "reconstructed",
        transform: { translation_xyz: [1, 2, 0.3], rotation_quaternion_xyzw: [0, 0, 0, 1] },
        primitive_dimensions_xyz_m: [1, 0.8, 0.6],
        geometry_ref: ref,
        provenance: review ? { review } : {},
      },
    ],
  };
}

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

describe("ObjectReviewView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("xác nhận ứng viên với revision hiện tại và hiển thị revision mới", async () => {
    vi.mocked(global.fetch)
      .mockResolvedValueOnce(reply({ scene: scene("rev-001", "CANDIDATE") }))
      .mockResolvedValueOnce(reply({ scene_revision: "rev-002", scene: scene("rev-002", "CONFIRMED", "CONFIRMED") }));
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText("1 vật thể · 1 chờ xác nhận")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Xác nhận/ }));
    await waitFor(() => expect(screen.getByText("Đã xác nhận")).toBeInTheDocument());
    const [url, init] = vi.mocked(global.fetch).mock.calls[1]!;
    expect(String(url)).toContain("/api/v1/jobs/job-a/scene/objects/candidate-001/confirm");
    expect(JSON.parse((init as RequestInit).body as string).expected_scene_revision).toBe("rev-001");
  });

  it("ẩn ứng viên đã loại trừ khi bật hiển thị", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply({ scene: scene("rev-003", "CANDIDATE", "IGNORED") }));
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText("1 vật thể · 0 chờ xác nhận")).toBeInTheDocument();
    expect(screen.queryByText("Vật thể 1")).toBeNull();
    fireEvent.click(screen.getByLabelText("Hiện cả ứng viên đã loại"));
    expect(screen.getByText("Đã loại")).toBeInTheDocument();
  });

  it("báo rõ khi bước tách vật thể chưa có scene", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(reply({ detail: "Job chưa publish SceneIR" }, 404));
    render(<ObjectReviewView jobId="job-a" />);
    expect(await screen.findByText(/Chưa có vật thể/)).toBeInTheDocument();
  });
});
