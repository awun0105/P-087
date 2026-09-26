/**
 * Test cho AddObstacleForm (PRODUCT-07A).
 *
 * Kiểm tra validation client-side và payload gửi đi qua mock fetch.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddObstacleForm } from "@/features/scene/AddObstacle";

describe("AddObstacleForm", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("từ chối khi tên trống", async () => {
    render(<AddObstacleForm jobId="job-fixture-001" sceneRevision="rev-001" onDone={vi.fn()} />);
    fireEvent.submit(screen.getByRole("button", { name: /Thêm vào scene/ }));
    expect(await screen.findByTestId("add-obstacle-error")).toHaveTextContent("Tên object không được để trống");
  });

  it("từ chối khi kích thước không phải số dương", async () => {
    render(<AddObstacleForm jobId="job-fixture-001" sceneRevision="rev-001" onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Tên object"), { target: { value: "Box" } });
    fireEvent.change(screen.getByLabelText("Chiều rộng"), { target: { value: "-1" } });
    fireEvent.submit(screen.getByRole("button", { name: /Thêm vào scene/ }));
    expect(await screen.findByTestId("add-obstacle-error")).toHaveTextContent("Kích thước");
  });

  it("gửi payload đúng khi hợp lệ", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ scene_revision: "rev-002" }),
    } as Response);

    render(<AddObstacleForm jobId="job-fixture-001" sceneRevision="rev-001" onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Tên object"), { target: { value: "New Box" } });
    fireEvent.change(screen.getByLabelText("X"), { target: { value: "1.5" } });
    fireEvent.change(screen.getByLabelText("Y"), { target: { value: "0.0" } });
    fireEvent.change(screen.getByLabelText("Z"), { target: { value: "-2.0" } });

    fireEvent.submit(screen.getByRole("button", { name: /Thêm vào scene/ }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/jobs/job-fixture-001/scene/objects"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("New Box"),
        }),
      );
      const [, init] = vi.mocked(global.fetch).mock.calls[0]!;
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.expected_scene_revision).toBe("rev-001");
      expect(body.dimensions_xyz_m).toEqual([0.5, 0.5, 1.0]);
      expect(body.position_xyz).toEqual([1.5, 0.0, -2.0]);
      expect(body.collider_type).toBe("AABB");
    });
  });
});
