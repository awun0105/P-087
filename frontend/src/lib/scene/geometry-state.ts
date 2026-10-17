import type { SceneIR } from "@/lib/contracts/api";

/** `awaiting_review`: scene Draft đang chờ tạo mesh theo vật; `ready`: đã có collider theo vật. */
export type ObjectGeometryState = "awaiting_review" | "ready";

/** Lý do hiển thị (tooltip, banner) khi thao tác cần hình học bị khoá trong Draft. */
export const GEOMETRY_NOT_READY_REASON = "Cần tạo mesh trước";

/** Nhãn tiếng Việt của các phase tạo mesh (architecture.md §7.4). */
const GEOMETRY_PHASE_LABELS: Record<string, string> = {
  shell: "Dựng vỏ vật",
  quality: "Kiểm tra chất lượng",
  collider: "Tạo collider (CoACD)",
  objectgs: "Chạy ObjectGS",
  environment: "Dựng nền và collision môi trường",
  publish: "Lưu revision",
};

export function objectGeometryState(scene: Pick<SceneIR, "provenance">): ObjectGeometryState {
  const state = scene.provenance.object_geometry;
  // Thiếu khoá là scene cũ đã sẵn sàng. Giá trị lạ thì khoá lại, vì máy chủ cũng từ chối giá trị lạ.
  return state === undefined || state === "ready" ? "ready" : "awaiting_review";
}

/** Nhãn phase tiếng Việt; phase chưa biết giữ nguyên mã để không mất thông tin. */
export function geometryPhaseLabel(phase: string | null | undefined): string | null {
  if (!phase) return null;
  return GEOMETRY_PHASE_LABELS[phase] ?? phase;
}
