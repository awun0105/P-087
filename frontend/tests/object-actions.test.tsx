/**
 * Test cho ObjectActionsPanel (PRODUCT-07).
 *
 * Panel gọi fake endpoint `/scene/objects/{id}/{action}`. Test ở đây kiểm
 * payload gửi đi (mock fetch) và UI state (busy/error) — không chạm backend.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectActionsPanel } from "@/features/scene/ObjectActions";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));
import type { SceneObject } from "@/lib/contracts/api";

const FIXTURE_OBJECT: SceneObject = {
  id: "object-pallet-001",
  name: "Fixture Pallet",
  state: "CANDIDATE",
  origin: "reconstructed",
  active: true,
  visual_ref: null,
  asset_ref: null,
  primitive_dimensions_xyz_m: null,
  semantic_class: null,
  tags: [],
  local_frame: "pallet-frame",
  transform: {
    semantics: "parent_from_local",
    parent_frame: "world",
    local_frame: "pallet-frame",
    translation_xyz: [1.0, 0.0, -0.5],
    rotation_quaternion_xyzw: [0.0, 0.0, 0.0, 1.0],
    quaternion_order: "xyzw",
    angle_unit: "radian",
  },
  geometry_ref: {
    artifact_type: "PLY",
    schema_version: "1.0",
    artifact_uri: "artifact://jobs/job-fixture-001/scene/pallet.ply",
    artifact_checksum: "sha256:0000000000000000000000000000000000000000000000000000000000000001",
    data_class: "derived",
    producer_stage: "ST-SCENE",
    job_id: "job-fixture-001",
  },
  collider: null,
  provenance: {},
};

describe("ObjectActionsPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("gửi confirm action với expected_scene_revision", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ scene_revision: "rev-002" }),
    } as Response);

    const onDeselect = vi.fn();
    render(
      <ObjectActionsPanel
        jobId="job-fixture-001"
        sceneRevision="rev-001"
        object={FIXTURE_OBJECT}
        onDeselect={onDeselect}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Xác nhận/ }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/jobs/job-fixture-001/scene/objects/object-pallet-001/confirm"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("expected_scene_revision"),
        }),
      );
    });
  });

  it("hiện lỗi khi backend trả 409", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: "scene đã đổi" }),
    } as Response);

    render(
      <ObjectActionsPanel
        jobId="job-fixture-001"
        sceneRevision="rev-001"
        object={FIXTURE_OBJECT}
        onDeselect={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Xác nhận/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("409: scene đã đổi");
  });

  it("toggle active gửi payload active=false", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ scene_revision: "rev-002" }),
    } as Response);

    render(
      <ObjectActionsPanel
        jobId="job-fixture-001"
        sceneRevision="rev-001"
        object={FIXTURE_OBJECT}
        onDeselect={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Ẩn khỏi scene/ }));

    await waitFor(() => {
      const [, init] = vi.mocked(global.fetch).mock.calls[0]!;
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.active).toBe(false);
    });
  });

  it("xóa object cần confirm trước khi gọi", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(
      <ObjectActionsPanel
        jobId="job-fixture-001"
        sceneRevision="rev-001"
        object={FIXTURE_OBJECT}
        onDeselect={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Xóa object/ }));
    expect(confirmSpy).toHaveBeenCalledWith('Xóa "Fixture Pallet" khỏi revision? Không hoàn tác.');
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
