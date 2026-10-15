/**
 * Lớp phủ Region Editor trong viewport Studio (T-015): vẽ box chọn Gaussian gắn theo vật, tay nắm mặt, gizmo xoay
 * quanh Z và dịch tâm, và góc nhìn. Mọi thay đổi box đi qua box model (T-014); lớp này không tự tính hình học.
 *
 * Gốc overlay là con của entity vật, nên box theo pose hiện tại của vật, còn giá trị lưu vẫn là object-local.
 */
import {
  AppBase,
  BLEND_NONE,
  BLEND_NORMAL,
  CULLFACE_NONE,
  Color,
  Entity,
  Mesh,
  MeshInstance as PcMeshInstance,
  PRIMITIVE_TRIANGLES,
  Quat,
  StandardMaterial,
} from "playcanvas";

import type { BoxOp, EditableBox, Vec3 } from "@/features/studio/region/box-model";
import type { SceneOverlay } from "@/features/viewer/scene-overlay";

export interface RegionOverlayHandlers {
  /** Gọi khi thả tay nắm hoặc gizmo, không gọi lúc đang kéo. Nhận toàn bộ danh sách box, đã qua clamp sàn. */
  onChange(boxes: EditableBox[]): void;
  onSelect(boxId: string | null): void;
}

export type ViewPreset = "top" | "front" | "side";

/** Phần của SceneOverlay mà lớp vùng dùng. `SceneOverlay` thoả kiểu này; test đưa bản giả vào. */
export type RegionHost = Pick<
  SceneOverlay,
  "isAlive" | "application" | "activeCamera" | "objectEntity" | "sharedGizmoLayer" | "requestFrame" | "gotoPose"
>;

const ADD_COLOR = "#22c55e";
const SUBTRACT_COLOR = "#ef4444";
const FACE_OPACITY = 0.08;
const EDGE_THICKNESS_M = 0.006;
const SELECTED_EDGE_THICKNESS_M = 0.014;
const DASH_LENGTH_M = 0.12;
const DASH_GAP_M = 0.08;

function copyVec3(v: Vec3): Vec3 {
  return [v[0], v[1], v[2]];
}

/** Quaternion quay quanh +Z (xyzw), khớp quy ước yaw của box model. */
function yawQuat(yaw: number): Quat {
  return new Quat(0, 0, Math.sin(yaw / 2), Math.cos(yaw / 2));
}

/** Đoạn [from, to] của một cạnh; cạnh box trừ được chia thành nét đứt. */
function edgeSegments(lo: number, hi: number, dashed: boolean): Array<[number, number]> {
  if (!dashed) return [[lo, hi]];
  const segments: Array<[number, number]> = [];
  let from = lo;
  while (from < hi) {
    const to = Math.min(from + DASH_LENGTH_M, hi);
    segments.push([from, to]);
    from = to + DASH_GAP_M;
  }
  return segments;
}

/** Thêm một hộp đặc (8 đỉnh, 12 tam giác) tâm `c`, nửa kích thước `e` vào lưới. */
function appendBox(positions: number[], indices: number[], c: Vec3, e: Vec3): void {
  const base = positions.length / 3;
  for (let i = 0; i < 8; i += 1) {
    const sx = i & 1 ? 1 : -1;
    const sy = i & 2 ? 1 : -1;
    const sz = i & 4 ? 1 : -1;
    positions.push(c[0] + sx * e[0], c[1] + sy * e[1], c[2] + sz * e[2]);
  }
  const quads = [
    [0, 1, 3, 2],
    [4, 6, 7, 5],
    [0, 4, 5, 1],
    [2, 3, 7, 6],
    [0, 2, 6, 4],
    [1, 5, 7, 3],
  ];
  for (const [a, b, d, f] of quads) indices.push(base + a, base + b, base + d, base + a, base + d, base + f);
}

/**
 * Khung 12 cạnh của box (object-local, tâm gốc) thành lưới tam giác: mỗi cạnh là một thanh vuông `thickness`.
 * `dashed` chia cạnh thành nét đứt, dùng cho box trừ.
 */
export function edgeBars(half: Vec3, dashed: boolean, thickness: number): { positions: number[]; indices: number[] } {
  const positions: number[] = [];
  const indices: number[] = [];
  const reach = thickness / 2;
  for (let axis = 0; axis < 3; axis += 1) {
    const [u, v] = [0, 1, 2].filter((i) => i !== axis);
    for (const su of [-1, 1]) {
      for (const sv of [-1, 1]) {
        for (const [from, to] of edgeSegments(-half[axis], half[axis], dashed)) {
          const c: Vec3 = [0, 0, 0];
          c[axis] = (from + to) / 2;
          c[u] = su * half[u];
          c[v] = sv * half[v];
          const e: Vec3 = [reach, reach, reach];
          e[axis] = (to - from) / 2;
          appendBox(positions, indices, c, e);
        }
      }
    }
  }
  return { positions, indices };
}

/** Vật liệu trong suốt (mặt) hoặc đặc (cạnh), không đổ bóng, hai mặt. Cùng kiểu với `material` của scene-overlay. */
function regionMaterial(hex: string, opacity: number): StandardMaterial {
  const result = new StandardMaterial();
  result.diffuse = new Color(0, 0, 0);
  result.emissive = new Color().fromString(hex);
  result.useLighting = false;
  result.opacity = opacity;
  result.blendType = opacity < 1 ? BLEND_NORMAL : BLEND_NONE;
  result.depthWrite = opacity >= 1;
  result.cull = CULLFACE_NONE;
  result.update();
  return result;
}

interface BoxVisual {
  root: Entity;
  faces: Entity;
  edges: Entity;
  /** Khoá hình học: đổi op, chọn hoặc kích thước thì dựng lại mặt và cạnh. */
  key: string;
}

function styleKey(box: EditableBox, selected: boolean): string {
  return `${box.op}|${selected}|${box.half.join(",")}`;
}

export class RegionOverlay {
  private readonly app: AppBase;
  private readonly root: Entity;
  private readonly visuals = new Map<string, BoxVisual>();
  private readonly materials = new Map<string, StandardMaterial>();
  private boxes: EditableBox[] = [];
  private selectedId: string | null = null;
  private disposed = false;

  /** Gắn gốc overlay vào entity vật. Ném lỗi khi viewer chưa sẵn sàng hoặc vật chưa được nạp: không vẽ âm thầm. */
  constructor(
    private readonly host: RegionHost,
    objectId: string,
    private readonly handlers: RegionOverlayHandlers,
  ) {
    if (!host.isAlive()) throw new Error("RegionOverlay: viewer chưa sẵn sàng");
    const object = host.objectEntity(objectId);
    if (!object) throw new Error(`RegionOverlay: chưa có entity cho vật ${objectId}`);
    this.app = host.application();
    this.root = new Entity("r2s-region", this.app);
    object.addChild(this.root);
  }

  /** Vẽ lại toàn bộ box; `selectedId` không có trong danh sách thì coi như không chọn. */
  setBoxes(boxes: readonly EditableBox[], selectedId: string | null): void {
    if (!this.live()) return;
    this.boxes = boxes.map((box) => ({ ...box, center: copyVec3(box.center), half: copyVec3(box.half) }));
    this.selectedId = this.boxes.some((box) => box.id === selectedId) ? selectedId : null;
    this.sync();
  }

  /** Viewer đã sẵn sàng và lớp vẫn gắn trong scene. */
  private live(): boolean {
    return !this.disposed && this.host.isAlive() && this.root.parent !== null;
  }

  private sync(): void {
    const present = new Set<string>();
    for (const box of this.boxes) {
      present.add(box.id);
      const selected = box.id === this.selectedId;
      const visual = this.visuals.get(box.id);
      if (visual) {
        this.updateVisual(visual, box, selected);
      } else {
        this.visuals.set(box.id, this.createVisual(box, selected));
      }
    }
    for (const [id, visual] of this.visuals) {
      if (present.has(id)) continue;
      visual.root.destroy();
      this.visuals.delete(id);
    }
    this.host.requestFrame();
  }

  private createVisual(box: EditableBox, selected: boolean): BoxVisual {
    const root = new Entity(`region-box-${box.id}`, this.app);
    root.setLocalPosition(box.center[0], box.center[1], box.center[2]);
    root.setLocalRotation(yawQuat(box.yaw));
    this.root.addChild(root);
    const faces = this.createFaces(box);
    const edges = this.createEdges(box, selected);
    root.addChild(faces);
    root.addChild(edges);
    return { root, faces, edges, key: styleKey(box, selected) };
  }

  private updateVisual(visual: BoxVisual, box: EditableBox, selected: boolean): void {
    visual.root.setLocalPosition(box.center[0], box.center[1], box.center[2]);
    visual.root.setLocalRotation(yawQuat(box.yaw));
    const key = styleKey(box, selected);
    if (key === visual.key) return;
    visual.faces.destroy();
    visual.edges.destroy();
    visual.faces = this.createFaces(box);
    visual.edges = this.createEdges(box, selected);
    visual.root.addChild(visual.faces);
    visual.root.addChild(visual.edges);
    visual.key = key;
  }

  /** Mặt box: hộp đơn vị co giãn theo kích thước, trong suốt. */
  private createFaces(box: EditableBox): Entity {
    const faces = new Entity(`region-faces-${box.id}`, this.app);
    faces.addComponent("render", { type: "box", material: this.material("face", box.op), castShadows: false });
    faces.setLocalScale(2 * box.half[0], 2 * box.half[1], 2 * box.half[2]);
    return faces;
  }

  /** Viền box: lưới thanh tiết diện cố định (dày hơn khi được chọn), nét đứt nếu là box trừ. */
  private createEdges(box: EditableBox, selected: boolean): Entity {
    const bars = edgeBars(box.half, box.op === "subtract", selected ? SELECTED_EDGE_THICKNESS_M : EDGE_THICKNESS_M);
    const mesh = new Mesh(this.app.graphicsDevice);
    mesh.setPositions(bars.positions);
    mesh.setIndices(bars.indices);
    mesh.update(PRIMITIVE_TRIANGLES);
    const edges = new Entity(`region-edges-${box.id}`, this.app);
    edges.addComponent("render", {
      meshInstances: [new PcMeshInstance(mesh, this.material("edge", box.op))],
      castShadows: false,
    });
    return edges;
  }

  private material(kind: "face" | "edge", op: BoxOp): StandardMaterial {
    const key = `${kind}-${op}`;
    let found = this.materials.get(key);
    if (!found) {
      const hex = op === "add" ? ADD_COLOR : SUBTRACT_COLOR;
      found = regionMaterial(hex, kind === "face" ? FACE_OPACITY : 1);
      this.materials.set(key, found);
    }
    return found;
  }
}
