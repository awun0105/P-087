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
  RotateGizmo,
  StandardMaterial,
  TranslateGizmo,
  Vec3 as PcVec3,
} from "playcanvas";

import {
  boxesKey,
  clampToFloor,
  dragFace,
  faceCenter,
  faceNormal,
  rotateYaw,
  translateBox,
  type BoxOp,
  type EditableBox,
  type FaceId,
  type Vec3,
} from "@/features/studio/region/box-model";
import type { DisplayCameraPose } from "@/features/viewer/source-frame";
import {
  isolateGizmoPointer,
  isolatePointerGesture,
  rayUnitBox,
  type PointerGesture,
  type PointerIsolation,
  type SceneOverlay,
} from "@/features/viewer/scene-overlay";

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
const HANDLE_COLOR = "#ffffff";
const FACE_OPACITY = 0.08;
const EDGE_THICKNESS_M = 0.006;
const SELECTED_EDGE_THICKNESS_M = 0.014;
const DASH_LENGTH_M = 0.12;
const DASH_GAP_M = 0.08;
/** Tay nắm mặt rộng cỡ này trên màn hình, ở mọi khoảng cách. */
const HANDLE_PX = 14;
/** Bán kính bắt chuột quanh tâm tay nắm, theo pixel CSS. */
const HANDLE_HIT_PX = 9;
const FACE_IDS: readonly FaceId[] = ["+x", "-x", "+y", "-y", "+z", "-z"];
const FACE_AXIS: Record<FaceId, { axis: 0 | 1 | 2; sign: 1 | -1 }> = {
  "+x": { axis: 0, sign: 1 },
  "-x": { axis: 0, sign: -1 },
  "+y": { axis: 1, sign: 1 },
  "-y": { axis: 1, sign: -1 },
  "+z": { axis: 2, sign: 1 },
  "-z": { axis: 2, sign: -1 },
};

function copyVec3(v: Vec3): Vec3 {
  return [v[0], v[1], v[2]];
}

function toVec3(v: PcVec3): Vec3 {
  return [v.x, v.y, v.z];
}

function copyBox(box: EditableBox): EditableBox {
  return { ...box, center: copyVec3(box.center), half: copyVec3(box.half) };
}

function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

/** Quaternion quay quanh +Z (xyzw), khớp quy ước yaw của box model. */
function yawQuat(yaw: number): Quat {
  return new Quat(0, 0, Math.sin(yaw / 2), Math.cos(yaw / 2));
}

/** Yaw (quanh Z) của một entity, đọc từ quaternion của nó; đúng khi chỉ có quay quanh Z. */
function yawOf(root: Entity): number {
  const q = root.getLocalRotation();
  return 2 * Math.atan2(q.z, q.w);
}

/** Màu theo thao tác: cộng xanh lục, trừ đỏ. */
function colorOf(op: BoxOp): string {
  return op === "add" ? ADD_COLOR : SUBTRACT_COLOR;
}

/**
 * Tham số t của điểm trên đường thẳng `linePoint + t·lineDir` gần tia `origin + s·direction` nhất. Null khi song song.
 * Dùng để kéo tay nắm: khoảng dịch chuyển = t hiện tại − t lúc bấm.
 */
export function rayLineParam(origin: Vec3, direction: Vec3, linePoint: Vec3, lineDir: Vec3): number | null {
  const w: Vec3 = [origin[0] - linePoint[0], origin[1] - linePoint[1], origin[2] - linePoint[2]];
  const a = dot(direction, direction);
  const b = dot(direction, lineDir);
  const c = dot(lineDir, lineDir);
  const d = dot(direction, w);
  const e = dot(lineDir, w);
  const denom = a * c - b * b;
  if (Math.abs(denom) < 1e-12) return null;
  return (a * e - b * d) / denom;
}

/** Đường kính (m) của tay nắm để rộng `HANDLE_PX` pixel ở `distanceM`, với FOV dọc và chiều cao viewport. */
export function handleScale(distanceM: number, fovDeg: number, viewportHeightPx: number): number {
  const metersPerPixel = (2 * distanceM * Math.tan((fovDeg * Math.PI) / 360)) / viewportHeightPx;
  return HANDLE_PX * metersPerPixel;
}

/**
 * Vị trí tay nắm trong khung của box trước khi xoay: tâm của mặt, tức ±half trên trục tương ứng. Yaw đã có sẵn trong
 * transform của box nên không áp lại ở đây.
 */
function handleOffset(half: Vec3, face: FaceId): Vec3 {
  const { axis, sign } = FACE_AXIS[face];
  const offset: Vec3 = [0, 0, 0];
  offset[axis] = sign * half[axis];
  return offset;
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

/** Vật liệu trong suốt (mặt) hoặc đặc (cạnh, tay nắm), không đổ bóng, hai mặt. Cùng kiểu với `material` của scene-overlay. */
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

interface Handle {
  face: FaceId;
  entity: Entity;
}

/** Một lần kéo tay nắm đang diễn ra: box gốc lúc bấm và tham số của tia lúc bấm. */
interface FaceDrag {
  face: FaceId;
  original: EditableBox;
  before: EditableBox[];
  startParam: number;
}

/** Ba trục của khung box trong thế giới (đơn vị, đã gồm xoay của vật và của box). */
interface BoxAxes {
  x: Vec3;
  y: Vec3;
  z: Vec3;
}

function negate(v: Vec3): Vec3 {
  return [-v[0], -v[1], -v[2]];
}

/**
 * Pose camera nhìn vuông góc vào box, theo khung của chính box: `top` nhìn xuống −Z, `front` nhìn theo +Y, `side` nhìn
 * theo +X. Khoảng cách đủ để quả cầu bao box (bán kính `halfDiag`, cộng 20 %) vừa khung theo FOV dọc.
 */
export function viewPose(
  preset: ViewPreset,
  center: Vec3,
  axes: BoxAxes,
  halfDiag: number,
  fovDeg: number,
): DisplayCameraPose {
  const distance = (1.2 * halfDiag) / Math.sin((fovDeg * Math.PI) / 360);
  // Hướng từ tâm tới camera: `top` đứng trên trục z; `front` và `side` đứng ở phía âm của trục nhìn.
  const toward = preset === "top" ? axes.z : preset === "front" ? negate(axes.y) : negate(axes.x);
  return {
    position: [center[0] + toward[0] * distance, center[1] + toward[1] * distance, center[2] + toward[2] * distance],
    target: copyVec3(center),
    fov: fovDeg,
  };
}

function styleKey(box: EditableBox, selected: boolean): string {
  return `${box.op}|${selected}|${box.half.join(",")}`;
}

export class RegionOverlay {
  private readonly app: AppBase;
  private readonly canvas: HTMLCanvasElement;
  private readonly root: Entity;
  private readonly visuals = new Map<string, BoxVisual>();
  private readonly materials = new Map<string, StandardMaterial>();
  private readonly handles: Handle[];
  private readonly isolation: PointerIsolation;
  private faceDrag: FaceDrag | null = null;
  private boxes: EditableBox[] = [];
  private selectedId: string | null = null;
  private floorZ: number | null = null;
  private disposed = false;
  private rotateGizmo: RotateGizmo | null = null;
  private translateGizmo: TranslateGizmo | null = null;
  private rotateIsolation: PointerIsolation | null = null;
  private translateIsolation: PointerIsolation | null = null;
  /** Gốc của box đang gắn gizmo, hoặc null khi không chọn. */
  private gizmoTarget: Entity | null = null;
  /** Các box trước khi kéo gizmo, để trả lại nếu huỷ bằng Esc. */
  private gizmoDrag: EditableBox[] | null = null;
  private gizmoAborting = false;

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
    this.canvas = this.app.graphicsDevice.canvas;
    this.root = new Entity("r2s-region", this.app);
    object.addChild(this.root);
    this.handles = FACE_IDS.map((face) => {
      const entity = new Entity(`region-handle-${face}`, this.app);
      entity.addComponent("render", { type: "sphere", material: this.material("handle", HANDLE_COLOR, 1), castShadows: false });
      entity.enabled = false;
      return { face, entity };
    });
    this.isolation = isolatePointerGesture(this.canvas, this.faceGesture());
    this.canvas.addEventListener("pointerdown", this.onPointerDown);
    this.app.on("update", this.onUpdate);
  }

  /** Vẽ lại toàn bộ box; `selectedId` không có trong danh sách thì coi như không chọn. */
  setBoxes(boxes: readonly EditableBox[], selectedId: string | null): void {
    if (!this.live()) return;
    this.boxes = boxes.map(copyBox);
    this.selectedId = this.boxes.some((box) => box.id === selectedId) ? selectedId : null;
    this.sync();
  }

  /**
   * Đưa camera viewer tới góc nhìn của box đang chọn. Trả false khi không có box chọn, chưa có camera, hoặc viewer
   * chưa nối lệnh chuyển pose (`SceneOverlay.bindViewerGotoPose`): không làm gì âm thầm.
   */
  viewFrom(preset: ViewPreset): boolean {
    const box = this.boxes.find((item) => item.id === this.selectedId);
    const root = this.selectedRoot();
    const camera = this.host.activeCamera();
    if (!box || !root || !camera || !this.live()) return false;
    const frame = root.getWorldTransform();
    const axes: BoxAxes = {
      x: toVec3(frame.transformVector(new PcVec3(1, 0, 0))),
      y: toVec3(frame.transformVector(new PcVec3(0, 1, 0))),
      z: toVec3(frame.transformVector(new PcVec3(0, 0, 1))),
    };
    const halfDiag = Math.hypot(box.half[0], box.half[1], box.half[2]);
    return this.host.gotoPose(viewPose(preset, toVec3(root.getPosition()), axes, halfDiag, camera.fov));
  }

  /**
   * Gỡ mọi thứ overlay đã thêm: entity khỏi scene, gizmo, listener trên canvas, cửa sổ và app, vật liệu. Sau khi gọi,
   * các lời gọi khác không làm gì; gọi lại cũng an toàn.
   */
  destroy(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.faceDrag = null;
    this.gizmoDrag = null;
    window.removeEventListener("keydown", this.onEscape);
    this.app.off("update", this.onUpdate);
    this.canvas.removeEventListener("pointerdown", this.onPointerDown);
    this.isolation.dispose();
    this.rotateIsolation?.dispose();
    this.translateIsolation?.dispose();
    this.rotateGizmo?.destroy();
    this.translateGizmo?.destroy();
    this.rotateGizmo = null;
    this.translateGizmo = null;
    this.rotateIsolation = null;
    this.translateIsolation = null;
    this.gizmoTarget = null;
    for (const handle of this.handles) handle.entity.destroy();
    for (const visual of this.visuals.values()) visual.root.destroy();
    this.visuals.clear();
    this.root.destroy();
    for (const material of this.materials.values()) material.destroy();
    this.materials.clear();
  }

  /** Mặt sàn (z, object-local). Khi thả, box không được xuống dưới sàn; chưa đặt sàn thì không kẹp. */
  setFloorZ(floorZ: number): void {
    this.floorZ = floorZ;
  }

  /** Đang có cử chỉ kéo (tay nắm hoặc gizmo): cập nhật box từ bên ngoài phải chờ đến khi thả. */
  isGesturing(): boolean {
    return this.faceDrag !== null || this.gizmoDrag !== null;
  }

  /** Viewer đã sẵn sàng và lớp vẫn gắn trong scene. */
  private live(): boolean {
    return !this.disposed && this.host.isAlive() && this.root.parent !== null;
  }

  private sync(): void {
    this.detachHandles();
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
      if (visual.root === this.gizmoTarget) this.attachGizmos(null);
      visual.root.destroy();
      this.visuals.delete(id);
    }
    this.placeHandles();
    this.attachGizmos(this.selectedRoot());
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
    const material = this.material(`face-${box.op}`, colorOf(box.op), FACE_OPACITY);
    faces.addComponent("render", { type: "box", material, castShadows: false });
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
      meshInstances: [new PcMeshInstance(mesh, this.material(`edge-${box.op}`, colorOf(box.op), 1))],
      castShadows: false,
    });
    return edges;
  }

  private material(key: string, hex: string, opacity: number): StandardMaterial {
    let found = this.materials.get(key);
    if (!found) {
      found = regionMaterial(hex, opacity);
      this.materials.set(key, found);
    }
    return found;
  }

  /** Gỡ tay nắm khỏi cây scene trước khi dựng lại box, để xoá một box không kéo theo tay nắm. */
  private detachHandles(): void {
    for (const handle of this.handles) {
      handle.entity.parent?.removeChild(handle.entity);
      handle.entity.enabled = false;
    }
  }

  /** Gắn tay nắm dưới box đang chọn, tại các mặt của nó, rồi chỉnh cỡ theo camera. */
  private placeHandles(): void {
    const box = this.boxes.find((item) => item.id === this.selectedId);
    const visual = box ? this.visuals.get(box.id) : undefined;
    if (!box || !visual) return;
    for (const handle of this.handles) {
      const offset = handleOffset(box.half, handle.face);
      visual.root.addChild(handle.entity);
      handle.entity.setLocalPosition(offset[0], offset[1], offset[2]);
      handle.entity.enabled = true;
    }
    this.scaleHandles();
  }

  /** Giữ tay nắm ~14 px trên màn hình khi camera di chuyển. */
  private scaleHandles(): void {
    const camera = this.host.activeCamera();
    const visual = this.selectedId ? this.visuals.get(this.selectedId) : undefined;
    if (!camera || !visual) return;
    const distance = camera.entity.getPosition().clone().distance(visual.root.getPosition());
    const size = handleScale(distance, camera.fov, this.app.graphicsDevice.clientRect.height);
    for (const handle of this.handles) handle.entity.setLocalScale(size, size, size);
  }

  /** Mặt có tay nắm nằm dưới con trỏ (trong bán kính bắt chuột), hoặc null. */
  private handleAt(x: number, y: number): FaceId | null {
    const camera = this.host.activeCamera();
    if (!camera || !this.live()) return null;
    for (const handle of this.handles) {
      if (!handle.entity.enabled) continue;
      const screen = camera.worldToScreen(handle.entity.getPosition());
      if (Math.hypot(screen.x - x, screen.y - y) <= HANDLE_HIT_PX) return handle.face;
    }
    return null;
  }

  /** Tia con trỏ trong khung object-local (khung gốc overlay), hoặc null khi chưa có camera. */
  private pointerRay(x: number, y: number): { origin: Vec3; direction: Vec3 } | null {
    const camera = this.host.activeCamera();
    if (!camera) return null;
    const toLocal = this.root.getWorldTransform().clone().invert();
    const near = toLocal.transformPoint(camera.entity.getPosition().clone(), new PcVec3());
    const far = toLocal.transformPoint(camera.screenToWorld(x, y, camera.farClip), new PcVec3());
    const direction = far.sub(near).normalize();
    return { origin: [near.x, near.y, near.z], direction: [direction.x, direction.y, direction.z] };
  }

  /** Box gần nhất dưới con trỏ, hoặc null. Tia đưa về khung đơn vị của mặt box (mặt có scale 2·half). */
  private pickBox(x: number, y: number): string | null {
    const camera = this.host.activeCamera();
    if (!camera) return null;
    const eye = camera.entity.getPosition().clone();
    const aim = camera.screenToWorld(x, y, camera.farClip).sub(eye).normalize();
    let best: string | null = null;
    let nearest = Infinity;
    for (const [id, visual] of this.visuals) {
      const inverse = visual.faces.getWorldTransform().clone().invert();
      const origin = inverse.transformPoint(eye, new PcVec3());
      const direction = inverse.transformVector(aim, new PcVec3());
      const hit = rayUnitBox([origin.x, origin.y, origin.z], [direction.x, direction.y, direction.z]);
      if (hit !== null && hit < nearest) {
        nearest = hit;
        best = id;
      }
    }
    return best;
  }

  /** Gizmo xoay (chỉ vòng Z) và dịch tâm: tạo một lần khi có camera, rồi gắn hoặc gỡ theo box đang chọn. */
  private ensureGizmos(): boolean {
    if (this.rotateGizmo && this.translateGizmo) return true;
    const camera = this.host.activeCamera();
    if (!camera) return false;
    const layer = this.host.sharedGizmoLayer();
    const rotate = new RotateGizmo(camera, layer);
    rotate.coordSpace = "local";
    // Chỉ còn vòng Z: các vòng khác vừa tắt tương tác, vừa ẩn hình (PlayCanvas chỉ làm mờ khi tắt).
    const shapes = (rotate as unknown as { _shapes: Record<string, { entity: Entity }> })._shapes;
    for (const [publicAxis, shape] of [
      ["x", "x"],
      ["y", "y"],
      ["face", "f"],
      ["xyz", "xyz"],
    ] as const) {
      rotate.enableShape(publicAxis, false);
      shapes[shape].entity.enabled = false;
    }
    const translate = new TranslateGizmo(camera, layer);
    translate.coordSpace = "local";
    rotate.on("transform:start", () => this.beginGizmoDrag());
    rotate.on("transform:move", () => this.host.requestFrame());
    rotate.on("transform:end", () => this.endGizmoDrag("rotate"));
    translate.on("transform:start", () => this.beginGizmoDrag());
    translate.on("transform:move", () => this.host.requestFrame());
    translate.on("transform:end", () => this.endGizmoDrag("translate"));
    this.rotateIsolation = isolateGizmoPointer(rotate, this.canvas);
    this.translateIsolation = isolateGizmoPointer(translate, this.canvas);
    this.rotateGizmo = rotate;
    this.translateGizmo = translate;
    return true;
  }

  /** Gắn gizmo vào gốc box đang chọn; `null` thì gỡ. Gốc giống lần trước thì không làm gì. */
  private attachGizmos(target: Entity | null): void {
    if (target === this.gizmoTarget) return;
    this.gizmoTarget = target;
    if (!target) {
      this.rotateGizmo?.detach();
      this.translateGizmo?.detach();
      return;
    }
    if (!this.ensureGizmos()) return;
    this.rotateGizmo?.attach([target]);
    this.translateGizmo?.attach([target]);
  }

  private selectedRoot(): Entity | null {
    const visual = this.selectedId ? this.visuals.get(this.selectedId) : undefined;
    return visual ? visual.root : null;
  }

  /** Gizmo bắt đầu kéo: nhớ các box để trả lại nếu huỷ bằng Esc. */
  private beginGizmoDrag(): void {
    this.gizmoDrag = this.snapshot();
    window.addEventListener("keydown", this.onEscape);
  }

  /**
   * Gizmo thả hoặc bị huỷ. Huỷ: trả box về như cũ, không báo ra ngoài. Thả: pose của entity (object-local) thành box
   * mới; chỉ báo ra ngoài khi box thật sự đổi.
   */
  private endGizmoDrag(kind: "rotate" | "translate"): void {
    const before = this.gizmoDrag;
    if (!before) return;
    this.gizmoDrag = null;
    window.removeEventListener("keydown", this.onEscape);
    if (this.gizmoAborting) {
      this.boxes = before;
      this.sync();
      return;
    }
    const selected = this.boxes.find((box) => box.id === this.selectedId);
    const root = this.selectedRoot();
    if (!selected || !root) return;
    const position = root.getLocalPosition();
    const moved =
      kind === "rotate"
        ? rotateYaw(selected, yawOf(root) - selected.yaw)
        : translateBox(selected, [
            position.x - selected.center[0],
            position.y - selected.center[1],
            position.z - selected.center[2],
          ]);
    this.boxes = this.boxes.map((box) => (box.id === moved.id ? this.settled(moved) : box));
    this.sync();
    if (boxesKey(this.boxes) !== boxesKey(before)) this.handlers.onChange(this.snapshot());
  }

  /** Box sau khi thả: không xuống dưới sàn nếu đã đặt sàn (đỉnh giữ nguyên, xem `clampToFloor`). */
  private settled(box: EditableBox): EditableBox {
    return this.floorZ === null ? box : clampToFloor(box, this.floorZ);
  }

  private snapshot(): EditableBox[] {
    return this.boxes.map(copyBox);
  }

  /** Cử chỉ kéo tay nắm: bắt bằng pointer ở pha capture, nên camera không thấy lúc đang kéo. */
  private faceGesture(): PointerGesture {
    return {
      hit: (e) => this.handleAt(e.offsetX, e.offsetY) !== null,
      press: (e) => this.beginFaceDrag(e.offsetX, e.offsetY),
      move: (e) => this.moveFaceDrag(e.offsetX, e.offsetY),
      release: () => this.endFaceDrag(),
      abort: () => this.revertFaceDrag(),
    };
  }

  private beginFaceDrag(x: number, y: number): void {
    const face = this.handleAt(x, y);
    const original = this.boxes.find((box) => box.id === this.selectedId);
    const ray = this.pointerRay(x, y);
    if (!face || !original || !ray) return;
    const startParam = rayLineParam(ray.origin, ray.direction, faceCenter(original, face), faceNormal(original, face));
    if (startParam === null) return;
    this.faceDrag = { face, original: copyBox(original), before: this.snapshot(), startParam };
    window.addEventListener("keydown", this.onEscape);
  }

  /** Xem trước khi kéo: box đổi ngay theo tia, nhưng chưa báo ra ngoài. */
  private moveFaceDrag(x: number, y: number): void {
    const drag = this.faceDrag;
    const ray = this.pointerRay(x, y);
    if (!drag || !ray) return;
    const param = rayLineParam(
      ray.origin,
      ray.direction,
      faceCenter(drag.original, drag.face),
      faceNormal(drag.original, drag.face),
    );
    if (param === null) return;
    const moved = dragFace(drag.original, drag.face, param - drag.startParam);
    this.boxes = this.boxes.map((box) => (box.id === moved.id ? moved : box));
    this.sync();
  }

  /** Thả tay nắm: chỉ báo ra ngoài khi box thật sự đổi. */
  private endFaceDrag(): void {
    const drag = this.faceDrag;
    if (!drag) return;
    this.faceDrag = null;
    window.removeEventListener("keydown", this.onEscape);
    this.boxes = this.boxes.map((box) => (box.id === drag.original.id ? this.settled(box) : box));
    this.sync();
    if (boxesKey(this.boxes) !== boxesKey(drag.before)) this.handlers.onChange(this.snapshot());
  }

  /** Huỷ kéo (Esc): trả box về trạng thái trước khi bấm, không báo ra ngoài. */
  private revertFaceDrag(): void {
    const drag = this.faceDrag;
    if (!drag) return;
    this.faceDrag = null;
    window.removeEventListener("keydown", this.onEscape);
    this.boxes = drag.before.map(copyBox);
    this.sync();
  }

  /** Bấm trái lên một box không phải tay nắm: chọn box đó. Nghe ở pha bubble, nên tay nắm đã nuốt sự kiện thì không tới đây. */
  private readonly onPointerDown = (e: PointerEvent): void => {
    if (!this.live() || e.button !== 0 || e.target !== this.canvas) return;
    const id = this.pickBox(e.offsetX, e.offsetY);
    if (id === null || id === this.selectedId) return;
    this.selectedId = id;
    this.sync();
    this.handlers.onSelect(id);
  };

  private readonly onUpdate = (): void => {
    if (this.live()) this.scaleHandles();
  };

  /** Esc huỷ mọi cử chỉ đang kéo: tay nắm mặt, hoặc gizmo (gizmo kết thúc qua transform:end và box được trả lại). */
  private readonly onEscape = (e: KeyboardEvent): void => {
    if (e.key !== "Escape") return;
    this.isolation.cancel();
    this.gizmoAborting = true;
    this.rotateIsolation?.cancel();
    this.translateIsolation?.cancel();
    this.gizmoAborting = false;
  };
}
