/**
 * Hàng ảo "Duyệt vật & Tạo mesh" (T-021): mỗi dòng của bảng trạng thái là một test; và việc dựng không còn làm hàng
 * "Tách vật thể" chạy lại.
 */

import { describe, expect, it } from "vitest";

import { fireEvent, render, screen } from "@testing-library/react";

import { PipelineTimeline } from "@/features/studio/PipelineTimeline";
import { GEOMETRY_REVIEW_STAGE, GEOMETRY_STAGE, OBJECT_STAGE } from "@/features/studio/stages";
import { geometryReviewStep, objectifyStageOverride } from "@/features/studio/scene/useObjectify";
import type { ObjectifyState } from "@/lib/api/studio";

function objectify(overrides: Partial<ObjectifyState>): ObjectifyState {
  return {
    status: "idle",
    mode: null,
    scene_revision: "rev-002",
    awaiting_choice: false,
    object_centric: true,
    available: true,
    note: null,
    base_revision: null,
    result_revision: null,
    error: null,
    resource_wait: null,
    cancellation_requested: false,
    object_geometry: "awaiting_review",
    ...overrides,
  };
}

describe("hàng Duyệt vật & Tạo mesh", () => {
  it("scene cũ không có khoá object_geometry: không có hàng", () => {
    expect(geometryReviewStep(objectify({ object_geometry: null }))).toBeNull();
    expect(geometryReviewStep(objectify({ object_geometry: undefined }))).toBeNull();
    expect(geometryReviewStep(null)).toBeNull();
  });

  it("Tạo mesh đang xếp hàng, chưa có phase: đang chạy, có thể huỷ", () => {
    expect(geometryReviewStep(objectify({ status: "queued", mode: "geometry", base_revision: "rev-002" }))).toEqual({
      state: "running",
      phase: null,
      error: null,
      mode: "geometry",
      cancelling: false,
      busy: true,
      rebuildFailed: false,
    });
  });

  it("Tạo mesh đang ở phase shell và đã xin huỷ: đang chạy, nêu đang dừng", () => {
    const step = geometryReviewStep(
      objectify({ status: "running", mode: "geometry", phase: "shell", cancellation_requested: true }),
    );
    expect(step).toMatchObject({ state: "running", phase: "shell", cancelling: true, busy: true });
  });

  it("dựng lại vùng đang chạy cũng là việc dựng: hàng đang chạy", () => {
    expect(geometryReviewStep(objectify({ status: "running", mode: "region", phase: "collider" }))).toMatchObject({
      state: "running",
      phase: "collider",
    });
  });

  it("Draft chờ duyệt, chưa có yêu cầu nào: chờ duyệt", () => {
    expect(geometryReviewStep(objectify({ status: "idle" }))).toMatchObject({ state: "waiting", busy: false });
  });

  it("Tạo mesh lỗi cùng revision: thất bại và giữ lý do của máy chủ", () => {
    const step = geometryReviewStep(
      objectify({
        status: "failed",
        mode: "geometry",
        base_revision: "rev-002",
        error: "Vỏ của Ghế không dựng được",
      }),
    );
    expect(step).toMatchObject({ state: "failed", error: "Vỏ của Ghế không dựng được", mode: "geometry" });
  });

  it("Tạo mesh bị huỷ cùng revision: thất bại để người dùng thử lại", () => {
    expect(geometryReviewStep(objectify({ status: "cancelled", mode: "geometry", base_revision: "rev-002" }))).toMatchObject({
      state: "failed",
    });
  });

  it("lỗi của revision cũ không còn là lỗi của scene hiện tại: vẫn chờ duyệt", () => {
    expect(
      geometryReviewStep(objectify({ status: "failed", mode: "geometry", base_revision: "rev-001", error: "cũ" })),
    ).toMatchObject({ state: "waiting" });
  });

  it("Ready: dựng lại vùng lỗi thì vẫn xong, nêu rằng scene giữ bản trước", () => {
    const step = geometryReviewStep(
      objectify({ object_geometry: "ready", status: "failed", mode: "region", error: "vùng không hợp lệ" }),
    );
    expect(step).toMatchObject({ state: "succeeded", rebuildFailed: true, error: "vùng không hợp lệ" });
  });

  it("Ready bình thường: xong, không có lỗi", () => {
    expect(geometryReviewStep(objectify({ object_geometry: "ready", status: "done" }))).toMatchObject({
      state: "succeeded",
      rebuildFailed: false,
      error: null,
    });
  });
});

describe("hàng Tách vật thể không chạy lại vì việc dựng", () => {
  it("Tạo mesh đang xếp hàng không làm hàng Tách vật thể chạy", () => {
    expect(objectifyStageOverride(objectify({ status: "queued", mode: "geometry" }))).toBeNull();
  });

  it("tách vật và hộp ứng viên đang chạy vẫn làm hàng Tách vật thể chạy", () => {
    expect(objectifyStageOverride(objectify({ status: "running", mode: "objectify" }))).toEqual({ state: "running" });
    expect(objectifyStageOverride(objectify({ status: "queued", mode: "boxes" }))).toEqual({ state: "running" });
  });
});

describe("chữ mô tả bước và hàng ảo trên timeline", () => {
  it("bước Collision và Tách vật thể mô tả đúng việc từng bước làm; hàng ảo có tên Duyệt vật & Tạo mesh", () => {
    expect(GEOMETRY_STAGE.title).toBe("Collision môi trường");
    expect(GEOMETRY_STAGE.description).toContain("Collider riêng của từng vật được tạo sau, ở bước Tạo mesh.");
    expect(OBJECT_STAGE.description).toContain("kèm vỏ thô để bạn duyệt. Chưa vá nền và chưa có collider.");
    expect(OBJECT_STAGE.description).not.toContain("Máy không có runtime");
    expect(GEOMETRY_REVIEW_STAGE).toMatchObject({ id: "UI-GEOMETRY-REVIEW", title: "Duyệt vật & Tạo mesh", short: "Tạo mesh" });
    expect(GEOMETRY_REVIEW_STAGE.description).toContain("chưa Walk hay xuất USD được");
  });

  it("hàng ảo không có tiêu đề bấm được và không có link Xem giai đoạn; hàng stage thật vẫn có", () => {
    render(
      <PipelineTimeline
        jobId="job-a"
        stageList={[OBJECT_STAGE, GEOMETRY_REVIEW_STAGE]}
        stages={[
          { stage_id: OBJECT_STAGE.id, state: "succeeded", seconds: 12, fraction: null },
          { stage_id: GEOMETRY_REVIEW_STAGE.id, state: "succeeded", seconds: null, fraction: null },
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: "Duyệt vật & Tạo mesh" })).not.toBeInTheDocument();
    expect(screen.getByText("Duyệt vật & Tạo mesh")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Tách vật thể/ }));
    expect(screen.getByRole("link", { name: /Xem giai đoạn/ })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Xem giai đoạn/ })).toHaveLength(1);
  });
});
