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

const FACES: Record<FaceId, { axis: Axis; sign: 1 | -1 }> = {
  "+x": { axis: 0, sign: 1 },
  "-x": { axis: 0, sign: -1 },
  "+y": { axis: 1, sign: 1 },
  "-y": { axis: 1, sign: -1 },
  "+z": { axis: 2, sign: 1 },
  "-z": { axis: 2, sign: -1 },
};

function clampHalf(half: number): number {
  return Math.min(MAX_HALF_M, Math.max(MIN_HALF_M, half));
}

function withComponent(v: Vec3, axis: Axis, value: number): Vec3 {
  const out = copyVec3(v);
  out[axis] = value;
  return out;
}

const TWO_PI = 2 * Math.PI;

/** Đưa góc về (-π, π]. */
function wrapYaw(angle: number): number {
  const wrapped = angle - TWO_PI * Math.floor((angle + Math.PI) / TWO_PI);
  return wrapped === -Math.PI ? Math.PI : wrapped;
}

/**
 * Kéo một mặt `deltaM` theo pháp tuyến ngoài của mặt đó; mặt đối diện đứng yên.
 * Nửa kích thước kẹp trong [MIN_HALF_M, MAX_HALF_M] và tâm chỉ dịch bằng phần đổi của nửa kích thước,
 * nên kéo âm quá mức thu box về MIN_HALF_M mà không đảo chiều.
 */
export function dragFace(box: EditableBox, face: FaceId, deltaM: number): EditableBox {
  const { axis, sign } = FACES[face];
  const half = clampHalf(box.half[axis] + deltaM / 2);
  const shift = sign * (half - box.half[axis]);
  const e = axisDirection(box.yaw, axis);
  return {
    ...box,
    center: [box.center[0] + e[0] * shift, box.center[1] + e[1] * shift, box.center[2] + e[2] * shift],
    half: withComponent(box.half, axis, half),
  };
}

/** Tịnh tiến tâm box, giữ nguyên kích thước và yaw. */
export function translateBox(box: EditableBox, delta: Vec3): EditableBox {
  return { ...box, center: [box.center[0] + delta[0], box.center[1] + delta[1], box.center[2] + delta[2]] };
}

/** Xoay quanh Z; góc sau khi cộng được chuẩn hoá về (-π, π]. */
export function rotateYaw(box: EditableBox, deltaRad: number): EditableBox {
  return { ...box, yaw: wrapYaw(box.yaw + deltaRad) };
}

/** Tâm của mặt trong object-local, dùng làm vị trí tay nắm. */
export function faceCenter(box: EditableBox, face: FaceId): Vec3 {
  const { axis, sign } = FACES[face];
  const e = axisDirection(box.yaw, axis);
  const offset = sign * box.half[axis];
  return [box.center[0] + e[0] * offset, box.center[1] + e[1] * offset, box.center[2] + e[2] * offset];
}

/** Pháp tuyến đơn vị hướng ra ngoài của mặt, trong object-local. */
export function faceNormal(box: EditableBox, face: FaceId): Vec3 {
  const { axis, sign } = FACES[face];
  const e = axisDirection(box.yaw, axis);
  return [sign * e[0], sign * e[1], sign * e[2]];
}

const DEFAULT_FIT_MARGIN_M = 0.02;

/**
 * Box mặc định bao quanh các điểm object-local (xyz phẳng). Yaw theo hướng chính trên mặt XY (PCA); cạnh dài hơn
 * là trục x. Đáy bám đúng z nhỏ nhất của điểm; mọi nửa kích thước cộng `marginM`, nên đỉnh cao hơn điểm cao nhất
 * 2·marginM. Nửa kích thước kẹp trong [MIN_HALF_M, MAX_HALF_M]. Ném lỗi khi không có điểm.
 */
export function fitBoxToPoints(points: Float32Array, marginM = DEFAULT_FIT_MARGIN_M): Omit<EditableBox, "id" | "op"> {
  if (points.length === 0 || points.length % 3 !== 0) throw new Error("fitBoxToPoints cần mảng xyz với ít nhất một điểm");
  const count = points.length / 3;
  let sumX = 0;
  let sumY = 0;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i < points.length; i += 3) {
    sumX += points[i];
    sumY += points[i + 1];
    minZ = Math.min(minZ, points[i + 2]);
    maxZ = Math.max(maxZ, points[i + 2]);
  }
  const meanX = sumX / count;
  const meanY = sumY / count;
  let sxx = 0;
  let syy = 0;
  let sxy = 0;
  for (let i = 0; i < points.length; i += 3) {
    const dx = points[i] - meanX;
    const dy = points[i + 1] - meanY;
    sxx += dx * dx;
    syy += dy * dy;
    sxy += dx * dy;
  }
  // Trục chính trên mặt XY: tan 2φ = 2·sxy / (sxx − syy).
  const phi = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  const u = [Math.cos(phi), Math.sin(phi)];
  const v = [-Math.sin(phi), Math.cos(phi)];
  let minU = Infinity;
  let maxU = -Infinity;
  let minV = Infinity;
  let maxV = -Infinity;
  for (let i = 0; i < points.length; i += 3) {
    const pu = points[i] * u[0] + points[i + 1] * u[1];
    const pv = points[i] * v[0] + points[i + 1] * v[1];
    minU = Math.min(minU, pu);
    maxU = Math.max(maxU, pu);
    minV = Math.min(minV, pv);
    maxV = Math.max(maxV, pv);
  }
  const extU = maxU - minU;
  const extV = maxV - minV;
  // Trục x là trục có extent lớn hơn; yaw của nó được đưa về (-π/2, π/2].
  let yaw = extU >= extV ? phi : phi + Math.PI / 2;
  if (yaw > Math.PI / 2) yaw -= Math.PI;
  const midU = (minU + maxU) / 2;
  const midV = (minV + maxV) / 2;
  const half: Vec3 = [
    clampHalf(Math.max(extU, extV) / 2 + marginM),
    clampHalf(Math.min(extU, extV) / 2 + marginM),
    clampHalf((maxZ - minZ) / 2 + marginM),
  ];
  return {
    center: [midU * u[0] + midV * v[0], midU * u[1] + midV * v[1], minZ + half[2]],
    half,
    yaw,
  };
}

/**
 * Không cho đáy box xuống dưới `floorZ` (object-local). Giữ đỉnh cố định và giảm nửa chiều cao; nếu đỉnh quá sát
 * sàn thì giữ MIN_HALF_M và nâng đỉnh lên, vì sàn là ràng buộc cứng.
 */
export function clampToFloor(box: EditableBox, floorZ: number): EditableBox {
  const bottom = box.center[2] - box.half[2];
  if (bottom >= floorZ) return { ...box };
  const top = box.center[2] + box.half[2];
  const half = clampHalf((top - floorZ) / 2);
  return { ...box, center: [box.center[0], box.center[1], floorZ + half], half: withComponent(box.half, 2, half) };
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

/** Lượng tử hoá 1e-7 m (rad): nhiễu số thực không đổi khoá, còn thay đổi ≥ 1e-6 luôn đổi khoá. */
const KEY_SCALE = 1e7;

/**
 * Chuỗi ổn định mô tả hình học của tập box, để so preview với box hiện tại. Không gồm id (chỉ có ở UI) và được
 * dựng từ từng trường theo thứ tự cố định, nên thứ tự thuộc tính của object không làm đổi khoá.
 */
export function boxesKey(boxes: EditableBox[]): string {
  return boxes
    .map((box) => `${box.op}:${[...box.center, ...box.half, box.yaw].map((v) => Math.round(v * KEY_SCALE)).join(",")}`)
    .join(";");
}
