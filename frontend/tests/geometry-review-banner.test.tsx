/**
 * Trạng thái hình học theo vật (T-013): khoá Draft, nhãn phase, và banner "Tạo mesh".
 */

import { describe, expect, it } from "vitest";

import type { SceneIR } from "@/lib/contracts/api";
import { GEOMETRY_NOT_READY_REASON, geometryPhaseLabel, objectGeometryState } from "@/lib/scene/geometry-state";

const scene = (provenance: Record<string, unknown>) => ({ provenance }) as Pick<SceneIR, "provenance">;

describe("trạng thái hình học của scene", () => {
  it("thiếu khoá là scene cũ đã sẵn sàng", () => {
    expect(objectGeometryState(scene({}))).toBe("ready");
    expect(objectGeometryState(scene({ object_geometry: "ready" }))).toBe("ready");
  });

  it("awaiting_review là Draft; giá trị lạ bị khoá, không coi là sẵn sàng", () => {
    expect(objectGeometryState(scene({ object_geometry: "awaiting_review" }))).toBe("awaiting_review");
    expect(objectGeometryState(scene({ object_geometry: "building" }))).toBe("awaiting_review");
  });

  it("lý do khoá là câu cố định dùng cho tooltip", () => {
    expect(GEOMETRY_NOT_READY_REASON).toBe("Cần tạo mesh trước");
  });

  it("phase tạo mesh hiện bằng tiếng Việt, phase lạ giữ nguyên mã", () => {
    expect(geometryPhaseLabel("shell")).toBe("Dựng vỏ vật");
    expect(geometryPhaseLabel("collider")).toBe("Tạo collider (CoACD)");
    expect(geometryPhaseLabel("environment")).toBe("Dựng nền và collision môi trường");
    expect(geometryPhaseLabel("publish")).toBe("Lưu revision");
    expect(geometryPhaseLabel("new_phase")).toBe("new_phase");
    expect(geometryPhaseLabel(null)).toBeNull();
  });
});
