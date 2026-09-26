/**
 * Test cho SceneGraph và MetricScalePanel (PRODUCT-06 UI nâng cấp).
 *
 * Khoá các hành vi mới:
 * - SceneGraph chỉ hiển thị filter tab All/Candidate/Confirmed (không bịa thêm trạng thái).
 * - MetricScalePanel render đúng giá trị thật từ SceneIR.metric_scale.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SceneGraph } from "@/features/scene/SceneGraph";
import { MetricScalePanel } from "@/features/scene/MetricScalePanel";
import { MockReadonlyPanel } from "@/features/scene/MockReadonlyPanel";
import { sceneIR } from "./fixtures/scene";

const scene = sceneIR();

describe("SceneGraph", () => {
  it("hiển thị object và filter đúng theo state", () => {
    const onSelect = vi.fn();
    render(<SceneGraph scene={scene} selectedObjectId={null} onSelect={onSelect} />);

    expect(screen.getByRole("button", { name: "All" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Candidate" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Confirmed" })).toBeDefined();
    expect(screen.getByText("Fixture Pallet")).toBeDefined();
  });

  it("click object gọi onSelect với id", () => {
    const onSelect = vi.fn();
    render(<SceneGraph scene={scene} selectedObjectId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("Fixture Pallet"));
    expect(onSelect).toHaveBeenCalledWith("object-pallet-001");
  });

  it("filter Candidate ẩn object CONFIRMED", () => {
    const onSelect = vi.fn();
    render(<SceneGraph scene={scene} selectedObjectId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "Candidate" }));
    expect(screen.queryByText("Fixture Pallet")).toBeNull();
  });
});

describe("MetricScalePanel", () => {
  it("hiển thị UNCONFIRMED từ fixture", () => {
    render(<MetricScalePanel metricScale={scene.metric_scale} />);
    expect(screen.getByText("UNCONFIRMED")).toBeDefined();
    expect(screen.getByText("chưa xác định")).toBeDefined();
    expect(screen.getByText(/Alignment chưa có backend/i)).toBeDefined();
  });
});

describe("MockReadonlyPanel", () => {
  it("hiển thị nhãn mock rõ ràng", () => {
    render(<MockReadonlyPanel title="Audit" reason="backend chưa có endpoint." />);
    expect(screen.getByText("Chưa có backend")).toBeDefined();
    expect(screen.getByText(/backend chưa có endpoint/i)).toBeDefined();
  });
});
