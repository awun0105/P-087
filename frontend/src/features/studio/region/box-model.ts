/**
 * Toán của region box chọn Gaussian thuộc vật (T-014). Thuần TypeScript: không import PlayCanvas, không gọi API.
 *
 * Toạ độ canonical Z-up, mét, box ở object-local. Yaw là góc quay quanh +Z: trục x cục bộ = (cos yaw, sin yaw, 0),
 * trục y cục bộ = (−sin yaw, cos yaw, 0). Mọi hàm trả object mới, không sửa đầu vào.
 */

export type Vec3 = [number, number, number];
export type BoxOp = "add" | "subtract";

export interface EditableBox {
  id: string;
  op: BoxOp;
  center: Vec3;
  /** Nửa kích thước theo trục cục bộ x, y, z. */
  half: Vec3;
  yaw: number;
}

export type FaceId = "+x" | "-x" | "+y" | "-y" | "+z" | "-z";

/** Dạng gửi lên API (architecture §7.3). Khai báo cục bộ cho tới khi T-004 đưa mirror vào `api.ts`. */
export interface RegionBox {
  op: BoxOp;
  center_m: Vec3;
  half_extents_m: Vec3;
  yaw_rad: number;
}

export const MIN_HALF_M = 0.005;
export const MAX_HALF_M = 20;
export const MAX_BOXES = 16;

/** Dung sai tuyệt đối khi kiểm điểm nằm trên mặt box, khớp quy tắc server. */
const CONTAINS_TOLERANCE_M = 1e-6;

type Axis = 0 | 1 | 2;

/** Trục cục bộ thứ `axis` của box có yaw cho trước, trong object-local. */
function axisDirection(yaw: number, axis: Axis): Vec3 {
  if (axis === 0) return [Math.cos(yaw), Math.sin(yaw), 0];
  if (axis === 1) return [-Math.sin(yaw), Math.cos(yaw), 0];
  return [0, 0, 1];
}

function copyVec3(v: Vec3): Vec3 {
  return [v[0], v[1], v[2]];
}

/** Điểm object-local nằm trong box (bỏ qua op: cộng/trừ do server xử lý). */
export function contains(box: EditableBox, p: Vec3): boolean {
  const d: Vec3 = [p[0] - box.center[0], p[1] - box.center[1], p[2] - box.center[2]];
  for (const axis of [0, 1, 2] as const) {
    const e = axisDirection(box.yaw, axis);
    const along = d[0] * e[0] + d[1] * e[1] + d[2] * e[2];
    // Phủ định để NaN rơi vào nhánh từ chối.
    if (!(Math.abs(along) <= box.half[axis] + CONTAINS_TOLERANCE_M)) return false;
  }
  return true;
}

/** Chuyển sang dạng gửi API, giữ thứ tự; `id` là trạng thái UI nên không gửi. */
export function toCommandBoxes(boxes: EditableBox[]): RegionBox[] {
  return boxes.map((box) => ({
    op: box.op,
    center_m: copyVec3(box.center),
    half_extents_m: copyVec3(box.half),
    yaw_rad: box.yaw,
  }));
}

/** Thông báo lỗi tiếng Việt cho người dùng, hoặc null khi tập box hợp lệ. */
export function validateBoxes(boxes: EditableBox[]): string | null {
  if (!boxes.some((box) => box.op === "add")) return "Cần ít nhất một box cộng";
  if (boxes.length > MAX_BOXES) return `Tối đa ${MAX_BOXES} box`;
  for (const [index, box] of boxes.entries()) {
    const halfOk = box.half.every((h) => Number.isFinite(h) && h >= MIN_HALF_M && h <= MAX_HALF_M);
    if (!halfOk) return `Box ${index + 1}: nửa kích thước phải từ 0,005 m đến 20 m`;
    const placementOk = [...box.center, box.yaw].every((v) => Number.isFinite(v));
    if (!placementOk) return `Box ${index + 1}: tọa độ hoặc góc không hợp lệ`;
  }
  return null;
}
