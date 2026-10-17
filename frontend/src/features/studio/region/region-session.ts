/**
 * Phiên chỉnh vùng của một vật (T-016): danh sách box, box đang chọn và các vật được "Lấy luôn".
 * Thuần TypeScript: mọi hàm trả phiên mới, không sửa đầu vào.
 */

import type { EditableBox } from "@/features/studio/region/box-model";
import type { ViewPreset } from "@/features/viewer/region-overlay";
import type { RegionFit, RegionPreview } from "@/lib/api/studio";
import type { SceneObject } from "@/lib/contracts/api";

export interface RegionSession {
  objectId: string;
  boxes: EditableBox[];
  selectedId: string | null;
  /** Id các vật khác mà người dùng đồng ý lấy Gaussian ("Lấy luôn"). */
  claimFrom: string[];
}

/** Cầu nối từ panel tới overlay vùng trong viewer (MetricSceneView cung cấp). */
export interface RegionViewApi {
  viewFrom(preset: ViewPreset): boolean;
  isGesturing(): boolean;
  /**
   * Vỏ và điểm của lần xem trước trong viewer. `pending`: đang tính (làm mờ vỏ cũ). `preview` null và không pending:
   * trả vỏ gốc của vật và xoá điểm.
   */
  showPreview(objectId: string, preview: RegionPreview | null, pending: boolean): void;
}

/**
 * Box cộng ban đầu: bao đúng các Gaussian hiện có của vật (máy chủ tính, T-023). Không dựng từ kích thước primitive:
 * sau khi chỉnh lệch một phía, tâm nhóm không còn ở gốc nên box tâm 0 sẽ trả hàng về nền.
 */
export function initialRegionSession(object: SceneObject, fit: RegionFit): RegionSession {
  const box: EditableBox = {
    id: "add-1",
    op: "add",
    center: [...fit.center_m],
    half: [...fit.half_extents_m],
    yaw: fit.yaw_rad,
  };
  return { objectId: object.id, boxes: [box], selectedId: box.id, claimFrom: [] };
}

/** Nhãn hiển thị: "Cộng #1", "Trừ #2" theo vị trí trong danh sách. */
export function boxLabel(box: EditableBox, index: number): string {
  return `${box.op === "add" ? "Cộng" : "Trừ"} #${index + 1}`;
}

/** Box cộng cuối cùng không được xoá: không còn gì để giữ lại Gaussian. */
export function canRemoveBox(session: RegionSession, id: string): boolean {
  const box = session.boxes.find((item) => item.id === id);
  if (!box) return false;
  const addCount = session.boxes.filter((item) => item.op === "add").length;
  return !(box.op === "add" && addCount === 1);
}

/** Bật hoặc tắt "Lấy luôn" cho một vật chồng lấn; id chỉ xuất hiện một lần trong `claimFrom`. */
export function setRegionClaim(session: RegionSession, id: string, claimed: boolean): RegionSession {
  const others = session.claimFrom.filter((item) => item !== id);
  return { ...session, claimFrom: claimed ? [...others, id] : others };
}

export function selectRegionBox(session: RegionSession, id: string | null): RegionSession {
  return { ...session, selectedId: session.boxes.some((box) => box.id === id) ? id : null };
}

export function removeRegionBox(session: RegionSession, id: string): RegionSession {
  if (!canRemoveBox(session, id)) return session;
  const boxes = session.boxes.filter((box) => box.id !== id);
  const selectedId = session.selectedId === id ? (boxes[0]?.id ?? null) : session.selectedId;
  return { ...session, boxes, selectedId };
}

/** Box đang chọn, hoặc box cộng đầu tiên nếu chưa chọn: nguồn của các thao tác thêm box. */
function source(session: RegionSession): EditableBox | undefined {
  return session.boxes.find((box) => box.id === session.selectedId) ?? session.boxes.find((box) => box.op === "add");
}

function nextId(session: RegionSession, prefix: string): string {
  let n = session.boxes.length + 1;
  while (session.boxes.some((box) => box.id === `${prefix}-${n}`)) n += 1;
  return `${prefix}-${n}`;
}

/** "+ Box cộng": box mới thu còn 80% box nguồn, cùng tâm và yaw. */
export function addAddBox(session: RegionSession): RegionSession {
  const base = source(session);
  if (!base) return session;
  const box: EditableBox = {
    id: nextId(session, "add"),
    op: "add",
    center: [...base.center],
    half: [base.half[0] * 0.8, base.half[1] * 0.8, base.half[2] * 0.8],
    yaw: base.yaw,
  };
  return { ...session, boxes: [...session.boxes, box], selectedId: box.id };
}

/** "− Box trừ": box nhỏ 30% đặt ở tâm box nguồn. */
export function addSubtractBox(session: RegionSession): RegionSession {
  const base = source(session);
  if (!base) return session;
  const box: EditableBox = {
    id: nextId(session, "sub"),
    op: "subtract",
    center: [...base.center],
    half: [base.half[0] * 0.3, base.half[1] * 0.3, base.half[2] * 0.3],
    yaw: base.yaw,
  };
  return { ...session, boxes: [...session.boxes, box], selectedId: box.id };
}
