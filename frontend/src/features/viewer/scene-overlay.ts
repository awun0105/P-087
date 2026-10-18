/**
 * Lớp phủ trong cùng scene graph PlayCanvas với 3DGS: collision mesh REC-05 và hộp vật thể.
 *
 * Collision mesh và SceneIR đều ở hệ canonical Z-up (mét, sàn z = 0), nên mọi thứ gắn dưới một
 * entity gốc xoay theo `DISPLAY_EULER.z_up` — cùng phép xoay với splat hệ mét, không đổi dữ liệu.
 * Material, asset và entity do lớp này tạo đều được giải phóng trong `destroy()`.
 */

import {
  Asset,
  BLEND_NONE,
  BLEND_NORMAL,
  Color,
  CULLFACE_NONE,
  Entity,
  Gizmo,
  Mesh,
  MeshInstance as PcMeshInstance,
  PRIMITIVE_POINTS,
  PRIMITIVE_TRIANGLES,
  Quat,
  RENDERSTYLE_WIREFRAME,
  RENDERSTYLE_SOLID,
  RotateGizmo,
  StandardMaterial,
  TranslateGizmo,
  Vec3 as PcVec3,
  type AppBase,
  type CameraComponent,
  type ContainerResource,
  type Layer,
  type MeshInstance,
} from "playcanvas";

import type { CollisionSurfacePlane } from "@/lib/api/studio";
import { rotateVector, multiplyQuaternions } from "@/features/viewer/layers";
import { DISPLAY_EULER, type DisplayCameraPose, type Vec3 } from "@/features/viewer/source-frame";
import { themeColor } from "@/lib/theme";
import type { ViewerAppLike } from "@/features/viewer/PlayCanvasScene";

/**
 * Khoảng cách dọc tia (tham số t) tới lần chạm đầu với hộp đơn vị [-0,5; 0,5]³, hoặc null.
 * Tia đã đưa về khung local của hộp bằng ma trận nghịch đảo (gồm cả scale), nên t giữ nguyên ý
 * nghĩa như ở world và so được giữa các hộp.
 */
export function rayUnitBox(origin: Vec3, direction: Vec3): number | null {
  let near = -Infinity;
  let far = Infinity;
  for (let axis = 0; axis < 3; axis += 1) {
    if (Math.abs(direction[axis]) < 1e-12) {
      if (origin[axis] < -0.5 || origin[axis] > 0.5) return null;
      continue;
    }
    const a = (-0.5 - origin[axis]) / direction[axis];
    const b = (0.5 - origin[axis]) / direction[axis];
    near = Math.max(near, Math.min(a, b));
    far = Math.min(far, Math.max(a, b));
  }
  if (far < Math.max(near, 0)) return null;
  return near > 0 ? near : far;
}

/**
 * Khoảng cách dọc tia tới tam giác gần nhất của một lưới (Möller–Trumbore, cả hai mặt), hoặc null.
 * `positions` là xyz liên tiếp, `indices` là bộ ba chỉ số; tia và lưới cùng một khung toạ độ.
 */
export function rayTriangles(
  origin: Vec3,
  direction: Vec3,
  positions: ArrayLike<number>,
  indices: ArrayLike<number>,
): number | null {
  let nearest: number | null = null;
  const [ox, oy, oz] = origin;
  const [dx, dy, dz] = direction;
  for (let i = 0; i + 2 < indices.length; i += 3) {
    const a = indices[i] * 3;
    const b = indices[i + 1] * 3;
    const c = indices[i + 2] * 3;
    const e1x = positions[b] - positions[a];
    const e1y = positions[b + 1] - positions[a + 1];
    const e1z = positions[b + 2] - positions[a + 2];
    const e2x = positions[c] - positions[a];
    const e2y = positions[c + 1] - positions[a + 1];
    const e2z = positions[c + 2] - positions[a + 2];
    const px = dy * e2z - dz * e2y;
    const py = dz * e2x - dx * e2z;
    const pz = dx * e2y - dy * e2x;
    const det = e1x * px + e1y * py + e1z * pz;
    if (Math.abs(det) < 1e-12) continue; // tia song song mặt tam giác
    const inv = 1 / det;
    const tx = ox - positions[a];
    const ty = oy - positions[a + 1];
    const tz = oz - positions[a + 2];
    const u = (tx * px + ty * py + tz * pz) * inv;
    if (u < 0 || u > 1) continue;
    const qx = ty * e1z - tz * e1y;
    const qy = tz * e1x - tx * e1z;
    const qz = tx * e1y - ty * e1x;
    const v = (dx * qx + dy * qy + dz * qz) * inv;
    if (v < 0 || u + v > 1) continue;
    const distance = (e2x * qx + e2y * qy + e2z * qz) * inv;
    if (distance > 1e-9 && (nearest === null || distance < nearest)) nearest = distance;
  }
  return nearest;
}

/** Cử chỉ kéo bắt bằng pointer trên canvas, xem `isolatePointerGesture`. */
export interface PointerGesture {
  /** Bấm chuột trái có trúng điều khiển này không; trúng thì sự kiện bị nuốt để camera không thấy. */
  hit(e: PointerEvent): boolean;
  press(e: PointerEvent): void;
  /** Di chuyển lúc đang kéo; sự kiện đã bị nuốt. */
  move(e: PointerEvent): void;
  /** Di chuyển khi không kéo (hover); sự kiện không bị nuốt. */
  hover?(e: PointerEvent): void;
  release(e: PointerEvent): void;
  /** Huỷ giữa chừng: kết thúc cử chỉ mà không xác nhận thay đổi. `last` là sự kiện gần nhất, hoặc null. */
  abort?(last: PointerEvent | null): void;
}

export interface PointerIsolation {
  /** Gỡ mọi listener và trả pointer capture. */
  dispose(): void;
  /** Kết thúc cử chỉ đang kéo ngay (gọi `abort`) và trả quyền điều khiển cho camera. */
  cancel(): void;
}

/**
 * Cô lập cử chỉ kéo khỏi Camera Controller của supersplat-viewer. Controller nghe pointer ở pha bubble trên canvas
 * và đổi dịch chuyển chuột thành xoay/di chuyển camera. Listener ở pha CAPTURE chạy trước nên:
 * - Bấm trúng điều khiển: `stopImmediatePropagation()` để camera không thấy cử chỉ; move/up của cử chỉ đó cũng bị nuốt.
 * - Bấm ngoài điều khiển: sự kiện lan bình thường để xoay camera hoặc chọn vật.
 */
export function isolatePointerGesture(canvas: HTMLCanvasElement, gesture: PointerGesture): PointerIsolation {
  let dragging = false;
  let activePointerId: number | null = null;
  let lastEvent: PointerEvent | null = null;

  const releaseCapture = () => {
    if (activePointerId === null) return;
    try {
      if (canvas.hasPointerCapture?.(activePointerId)) {
        canvas.releasePointerCapture(activePointerId);
      }
    } catch {
      // Không lỗi nếu browser đã giải phóng trước
    }
  };

  const onCapturePointerDown = (e: PointerEvent) => {
    if (e.target !== canvas) return;
    if (typeof document !== "undefined" && document.pointerLockElement) return;
    if (e.button !== 0) return;
    if (!gesture.hit(e)) return;
    dragging = true;
    activePointerId = e.pointerId;
    lastEvent = e;
    e.stopImmediatePropagation();
    e.preventDefault();
    gesture.press(e);
  };

  const onCapturePointerMove = (e: PointerEvent) => {
    if (dragging && e.pointerId === activePointerId) {
      lastEvent = e;
      e.stopImmediatePropagation();
      e.preventDefault();
      gesture.move(e);
    } else if (!dragging) {
      gesture.hover?.(e);
    }
  };

  const onCapturePointerUp = (e: PointerEvent) => {
    if (dragging && (activePointerId === null || e.pointerId === activePointerId)) {
      dragging = false;
      activePointerId = null;
      e.stopImmediatePropagation();
      e.preventDefault();
      gesture.release(e);
    }
  };

  const onLostPointerCapture = (e: PointerEvent) => {
    if (dragging && (activePointerId === null || e.pointerId === activePointerId)) {
      dragging = false;
      activePointerId = null;
      gesture.release(e);
    }
  };

  canvas.addEventListener("pointerdown", onCapturePointerDown, { capture: true });
  canvas.addEventListener("pointermove", onCapturePointerMove, { capture: true });
  canvas.addEventListener("pointerup", onCapturePointerUp, { capture: true });
  canvas.addEventListener("pointercancel", onCapturePointerUp, { capture: true });
  canvas.addEventListener("lostpointercapture", onLostPointerCapture);

  return {
    dispose() {
      releaseCapture();
      dragging = false;
      activePointerId = null;
      canvas.removeEventListener("pointerdown", onCapturePointerDown, { capture: true });
      canvas.removeEventListener("pointermove", onCapturePointerMove, { capture: true });
      canvas.removeEventListener("pointerup", onCapturePointerUp, { capture: true });
      canvas.removeEventListener("pointercancel", onCapturePointerUp, { capture: true });
      canvas.removeEventListener("lostpointercapture", onLostPointerCapture);
    },
    cancel() {
      if (!dragging) return;
      releaseCapture();
      dragging = false;
      activePointerId = null;
      gesture.abort?.(lastEvent);
    },
  };
}

/**
 * Cô lập một Gizmo PlayCanvas khỏi Camera Controller. Gizmo tự nghe `pointerdown/move/up` ở pha bubble, nên gỡ các
 * listener đó rồi nối lại qua `isolatePointerGesture`: chỉ khi bấm trúng trục mới chuyển cử chỉ cho gizmo.
 */
export function isolateGizmoPointer(gizmo: TranslateGizmo | RotateGizmo, canvas: HTMLCanvasElement): PointerIsolation {
  type GizmoInternal = {
    _onPointerDown: (e: PointerEvent) => void;
    _onPointerMove: (e: PointerEvent) => void;
    _onPointerUp: (e: PointerEvent) => void;
    _getSelection: (x: number, y: number) => unknown[];
  };
  const internal = gizmo as unknown as GizmoInternal;
  canvas.removeEventListener("pointerdown", internal._onPointerDown);
  canvas.removeEventListener("pointermove", internal._onPointerMove);
  canvas.removeEventListener("pointerup", internal._onPointerUp);
  return isolatePointerGesture(canvas, {
    hit: (e) => gizmo.enabled && (internal._getSelection?.(e.offsetX, e.offsetY)?.length ?? 0) > 0,
    press: (e) => internal._onPointerDown(e),
    move: (e) => internal._onPointerMove(e),
    hover: (e) => internal._onPointerMove(e),
    release: (e) => internal._onPointerUp(e),
    abort: (last) => {
      if (last) internal._onPointerUp(last);
    },
  });
}

export interface OverlayBox {
  id: string;
  center: Vec3;
  rotation_xyzw: [number, number, number, number];
  dimensions: Vec3;
  /** Màu hex, vd `#22c55e`. */
  color: string;
  emphasized: boolean;
  /**
   * GLB trong collider-local frame. Vẽ và bắt chọn khung theo hình vật,
   * đồng thời cung cấp hình học cho lớp collider độc lập.
   */
  shapeUrl?: string | null;
  /** Object-local GLB used only to fit the selection box; never a physics collider. */
  boundsUrl?: string | null;
  colliderLocalTransform?: { translation_xyz: Vec3; rotation_quaternion_xyzw: [number, number, number, number] } | null;
}

/** Lưới của một hình dáng vật trong khung cục bộ của vật, dùng cho bắt chọn. */
interface ShapeGeometry {
  positions: Float32Array;
  indices: Uint32Array;
}

interface ShapeRecord {
  asset: Asset;
  geometry: ShapeGeometry | null;
  failed: boolean;
}

/** Một vật đang vẽ: `root` mang transform của vật; `box` là hộp lùi (đã scale) khi chưa có hình. */
interface Outline {
  localTransform?: OverlayBox["colliderLocalTransform"];
  id: string;
  root: Entity;
  box: Entity | null;
  shape: ShapeGeometry | null;
}

type RenderLike = { meshInstances: MeshInstance[] };

/** Gán material cho mọi mesh của một entity GLB; `wire` vẽ nét cạnh thay cho mặt. */
function paint(entity: Entity, fill: StandardMaterial, wire: boolean): void {
  for (const render of entity.findComponents("render") as unknown as RenderLike[]) {
    for (const instance of render.meshInstances) {
      instance.material = fill;
      if (wire && !instance.mesh.primitive[RENDERSTYLE_WIREFRAME]) instance.mesh.generateWireframe();
      instance.renderStyle = wire ? RENDERSTYLE_WIREFRAME : RENDERSTYLE_SOLID;
    }
  }
}

/**
 * Gộp mọi mesh của GLB thành một lưới trong khung gốc của GLB (đã áp transform của node), để tia
 * chọn vật thử trên đúng hình đang vẽ. Null khi GLB không có tam giác.
 */
function shapeGeometry(container: ContainerResource, rendered?: Entity): ShapeGeometry | null {
  const entity = rendered ?? container.instantiateRenderEntity();
  const positions: number[] = [];
  const indices: number[] = [];
  const point = new PcVec3();
  for (const render of entity.findComponents("render") as unknown as RenderLike[]) {
    for (const instance of render.meshInstances) {
      const local: number[] = [];
      const order: number[] = [];
      const count = instance.mesh.getPositions(local);
      instance.mesh.getIndices(order);
      const world = instance.node.getWorldTransform();
      const base = positions.length / 3;
      for (let i = 0; i < count; i += 1) {
        world.transformPoint(point.set(local[i * 3], local[i * 3 + 1], local[i * 3 + 2]), point);
        positions.push(point.x, point.y, point.z);
      }
      for (const index of order) indices.push(index + base);
    }
  }
  if (!rendered) entity.destroy();
  return indices.length >= 3 ? { positions: new Float32Array(positions), indices: new Uint32Array(indices) } : null;
}

function material(hex: string, opacity: number, lit: boolean): StandardMaterial {
  const result = new StandardMaterial();
  const color = new Color().fromString(hex);
  result.diffuse = lit ? color : new Color(0, 0, 0);
  result.emissive = lit ? new Color(0, 0, 0) : color;
  result.useLighting = lit;
  result.opacity = opacity;
  result.blendType = opacity < 1 ? BLEND_NORMAL : BLEND_NONE;
  result.depthWrite = opacity >= 1;
  result.cull = CULLFACE_NONE;
  result.update();
  return result;
}

/** Một vật của scene theo vật (pipeline v2): Gaussian riêng trong hệ cục bộ + transform của vật. */
export interface OverlayObject {
  id: string;
  /** URL hình riêng của vật; null với vật không có hình riêng (vật cản hộp, asset chưa có bản xem trước). */
  url: string | null;
  /** `gsplat` (mặc định): PLY Gaussian của vật tách từ scene. `model`: GLB hình khối của asset thư viện. */
  kind?: "gsplat" | "model";
  position: Vec3;
  rotation_xyzw: [number, number, number, number];
  visible: boolean;
}

export type GizmoMode = "translate" | "rotate";

export interface GizmoHandlers {
  onMove?(id: string, position: Vec3, rotation_xyzw: [number, number, number, number]): void;
  onStart(): void;
  /** Transform cục bộ của vật (hệ canonical Z-up, mét) khi người dùng thả gizmo. */
  onEnd(id: string, position: Vec3, rotation_xyzw: [number, number, number, number]): void;
}

export class SceneOverlay {
  private readonly app: AppBase;
  private readonly root: Entity;
  private readonly boxRoot: Entity;
  private readonly materials: StandardMaterial[] = [];
  private readonly surfaceRoot: Entity;
  private readonly surfaceMeshes: Mesh[] = [];
  private readonly surfaceMaterials: StandardMaterial[] = [];
  private surfaceInputs: readonly CollisionSurfacePlane[] | null = null;
  private readonly colliderRoot: Entity;
  private readonly colliderMaterials: StandardMaterial[] = [];
  private colliderOutlines: Outline[] = [];
  private colliderWire = false;
  private colliderInputs: readonly OverlayBox[] | null = null;
  private collisionGeneration = 0;
  private collisionAsset: Asset | null = null;
  private collisionEntity: Entity | null = null;
  private collisionGeometry: ShapeGeometry | null = null;
  private collisionGeometryUrl: string | null = null;
  private collisionMaterial: StandardMaterial | null = null;
  private outlines: Outline[] = [];
  private readonly shapes = new Map<string, ShapeRecord>();
  private readonly objectRoot: Entity;
  private readonly objects = new Map<string, { entity: Entity; asset: Asset | null; url: string | null }>();
  private pointsEntity: Entity | null = null;
  private pointsMesh: Mesh | null = null;
  private pointsMaterial: StandardMaterial | null = null;
  private gizmoLayer: Layer | null = null;
  private gizmo: TranslateGizmo | RotateGizmo | null = null;
  private gizmoCleanup: (() => void) | null = null;
  private viewerGotoPose: ((pose: DisplayCameraPose) => boolean) | null = null;
  private destroyed = false;

  /**
   * App còn dùng được: chưa `destroy()` và PlayCanvas chưa tự huỷ app (vd. mất WebGL device —
   * khi đó `app.root` thành null trước khi viewer kịp gọi `onApp(null)`).
   */
  private get alive(): boolean {
    return !this.destroyed && this.app.root != null;
  }

  constructor(app: ViewerAppLike) {
    this.app = app as unknown as AppBase;
    this.root = new Entity("r2s-overlay", this.app);
    const [x, y, z] = DISPLAY_EULER.z_up;
    this.root.setLocalEulerAngles(x, y, z);
    this.boxRoot = new Entity("r2s-boxes", this.app);
    this.root.addChild(this.boxRoot);
    this.colliderRoot = new Entity("r2s-colliders", this.app);
    this.root.addChild(this.colliderRoot);
    this.surfaceRoot = new Entity("r2s-surface-marks", this.app);
    this.root.addChild(this.surfaceRoot);
    this.objectRoot = new Entity("r2s-objects", this.app);
    this.root.addChild(this.objectRoot);
    // Splat không cần đèn; đèn này chỉ để mesh collision có khối (bóng theo mặt) khi nhìn.
    const light = new Entity("r2s-light", this.app);
    light.addComponent("light", { type: "directional", color: new Color(1, 1, 1), intensity: 1.1 });
    light.setLocalEulerAngles(45, 30, 0);
    this.root.addChild(light);
    this.app.root.addChild(this.root);
  }

  /** Nạp collision GLB (một lần); `opacity` < 1 để vẫn thấy 3DGS phía sau. */
  loadCollision(url: string, opacity: number): Promise<number> {
    this.releaseCollision();
    const generation = this.collisionGeneration;
    return new Promise((resolve, reject) => {
      const asset = new Asset(`r2s-collision-${url}`, "container", { url, filename: "collision.glb" });
      this.collisionAsset = asset;
      asset.once("load", () => {
        if (this.destroyed || generation !== this.collisionGeneration) return resolve(0);
        const entity = (asset.resource as ContainerResource).instantiateRenderEntity();
        this.collisionMaterial = material(themeColor("--studio-geometry", "#2f7ea8"), opacity, true);
        let triangles = 0;
        for (const render of entity.findComponents("render") as unknown as { meshInstances: { material: unknown; mesh: { primitive: { count: number }[] } }[] }[]) {
          for (const instance of render.meshInstances) {
            instance.material = this.collisionMaterial;
            triangles += (instance.mesh.primitive[0]?.count ?? 0) / 3;
          }
        }
        this.collisionGeometry = shapeGeometry(asset.resource as ContainerResource, entity);
        this.collisionGeometryUrl = url;
        this.collisionEntity = entity;
        this.root.addChild(entity);
        this.redraw();
        resolve(triangles);
      });
      asset.once("error", (error: unknown) => {
        if (generation === this.collisionGeneration) this.releaseCollision();
        reject(new Error(String(error)));
      });
      this.app.assets.add(asset);
      this.app.assets.load(asset);
    });
  }

  private releaseCollision(): void {
    this.collisionGeneration += 1;
    this.collisionEntity?.destroy();
    this.collisionEntity = null;
    this.collisionGeometry = null;
    this.collisionGeometryUrl = null;
    this.collisionMaterial?.destroy();
    this.collisionMaterial = null;
    if (this.collisionAsset) {
      this.app.assets?.remove(this.collisionAsset);
      this.collisionAsset.unload();
      this.collisionAsset = null;
    }
  }

  /**
   * Nạp lớp điểm (vd đám mây LiDAR) từ mảng `x y z` liên tiếp ở hệ canonical Z-up, mét. Gọi lại thì thay lớp cũ.
   * Điểm vẽ bằng màu phát sáng một tông để phân biệt với 3DGS; trả về số điểm.
   */
  setPoints(positions: Float32Array | null): number {
    if (!this.alive) return 0;
    this.releasePoints();
    if (!positions || positions.length < 3) {
      this.redraw();
      return 0;
    }
    const mesh = new Mesh(this.app.graphicsDevice);
    mesh.setPositions(positions);
    mesh.update(PRIMITIVE_POINTS);
    const fill = material(themeColor("--studio-marker-a", "#33ccff"), 1, false);
    const entity = new Entity("r2s-points", this.app);
    entity.addComponent("render", { meshInstances: [new PcMeshInstance(mesh, fill)], castShadows: false });
    this.root.addChild(entity);
    this.pointsEntity = entity;
    this.pointsMesh = mesh;
    this.pointsMaterial = fill;
    this.redraw();
    return positions.length / 3;
  }

  private releasePoints(): void {
    this.pointsEntity?.destroy();
    this.pointsMesh?.destroy();
    this.pointsMaterial?.destroy();
    this.pointsEntity = null;
    this.pointsMesh = null;
    this.pointsMaterial = null;
  }

  /**
   * Toạ độ đỉnh của lưới va chạm đã nạp, trong không gian hiển thị của viewer (đã áp phép xoay Z-up → Y-up).
   * Dùng cho các phép kiểm chặn phía trình duyệt (vd camera góc nhìn thứ ba); null khi chưa nạp lưới.
   */
  collisionPositions(): Float32Array | null {
    if (!this.alive || !this.collisionEntity) return null;
    const result: number[] = [];
    const point = new PcVec3();
    for (const render of this.collisionEntity.findComponents("render") as unknown as RenderLike[]) {
      for (const instance of render.meshInstances) {
        const local: number[] = [];
        const count = instance.mesh.getPositions(local);
        const world = instance.node.getWorldTransform();
        for (let i = 0; i < count; i += 1) {
          world.transformPoint(point.set(local[i * 3], local[i * 3 + 1], local[i * 3 + 2]), point);
          result.push(point.x, point.y, point.z);
        }
      }
    }
    return result.length ? new Float32Array(result) : null;
  }

  setCollision(visible: boolean, opacity: number, wire = false): void {
    if (!this.alive) return;
    if (this.collisionEntity) this.collisionEntity.enabled = visible;
    const current = this.collisionMaterial;
    if (!current) return this.redraw();
    if (this.collisionEntity) paint(this.collisionEntity, current, wire);
    current.opacity = wire ? 1 : opacity;
    current.blendType = current.opacity < 1 ? BLEND_NORMAL : BLEND_NONE;
    current.depthWrite = current.opacity >= 1;
    current.update();
    this.redraw();
  }

  /** Bật/tắt splat của viewer (entity upstream tên `gsplat`). */
  setSplatVisible(visible: boolean): void {
    if (!this.alive) return;
    const splat = this.app.root.findByName("gsplat");
    if (splat) splat.enabled = visible;
    this.redraw();
  }

  /**
   * Vẽ khung theo hình GLB của vật; dùng hộp khi không có GLB hoặc đang chờ tải.
   */
  setBoxes(boxes: readonly OverlayBox[]): void {
    if (!this.alive) return;
    for (const child of [...this.boxRoot.children]) child.destroy();
    this.releaseMaterials();
    this.outlines = boxes.map((box) => {
      const fill = material(box.color, box.emphasized ? 0.55 : 0.28, false);
      this.materials.push(fill);
      const root = new Entity(`r2s-box-${box.id}`, this.app);
      root.setLocalPosition(...box.center);
      root.setLocalRotation(new Quat(...box.rotation_xyzw));
      this.boxRoot.addChild(root);
      const outline: Outline = { localTransform: box.colliderLocalTransform, id: box.id, root, box: null, shape: null };
      const current = this.objects.get(box.id)?.entity;
      if (current) {
        const position = current.getLocalPosition();
        const rotation = current.getLocalRotation();
        this.setOutlinePose(outline, [position.x, position.y, position.z], [rotation.x, rotation.y, rotation.z, rotation.w]);
      }
      const fallback = new Entity(`r2s-box-fill-${box.id}`, this.app);
      fallback.addComponent("render", { type: "box", material: fill });
      fallback.setLocalScale(...box.dimensions);
      root.addChild(fallback);
      outline.box = fallback;
      const url = box.boundsUrl ?? box.shapeUrl;
      const record = url ? this.shape(url) : null;
      const applyGeometry = () => {
        if (!this.alive || !record?.geometry) return;
        if (box.boundsUrl) {
          const low: Vec3 = [Infinity, Infinity, Infinity];
          const high: Vec3 = [-Infinity, -Infinity, -Infinity];
          const positions = record.geometry.positions;
          for (let i = 0; i < positions.length; i += 3) {
            for (let axis = 0; axis < 3; axis++) {
              low[axis] = Math.min(low[axis], positions[i + axis]);
              high[axis] = Math.max(high[axis], positions[i + axis]);
            }
          }
          fallback.setLocalPosition((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, (low[2] + high[2]) / 2);
          fallback.setLocalScale(high[0] - low[0], high[1] - low[1], high[2] - low[2]);
        } else {
          fallback.destroy();
          outline.box = null;
          this.showSelectionShape(outline, record, fill, box.emphasized);
        }
      };
      if (record?.geometry) applyGeometry();
      else if (record && !record.failed) {
        record.asset.once("load", () => {
          if (!this.outlines.includes(outline)) return;
          applyGeometry();
          this.redraw();
        });
      }
      return outline;
    });
    this.redraw();
  }

  /** Show the selected source triangle: green floor, purple wall, fixed in canonical world. */
  setSurfaceMarkers(planes: readonly CollisionSurfacePlane[], visible: boolean): void {
    if (!this.alive) return;
    this.surfaceRoot.enabled = visible;
    if (planes === this.surfaceInputs) { this.redraw(); return; }
    this.surfaceInputs = planes;
    this.releaseSurfaceMarkers();
    for (const plane of planes) {
      const mesh = new Mesh(this.app.graphicsDevice);
      this.surfaceMeshes.push(mesh);
      mesh.setPositions(plane.points.flat());
      mesh.setIndices([0,1,2]);
      mesh.update(PRIMITIVE_TRIANGLES);
      const fill = material(plane.kind === "floor" ? themeColor("--studio-marker-floor", "#66e666") : themeColor("--studio-marker-check", "#e666e6"), 1, false);
      this.surfaceMaterials.push(fill);
      fill.depthTest = false;
      fill.depthWrite = false;
      fill.update();
      const entity = new Entity(`r2s-surface-${plane.id}`, this.app);
      entity.addComponent("render", {meshInstances:[new PcMeshInstance(mesh,fill)],castShadows:false});
      paint(entity,fill,true);
      this.surfaceRoot.addChild(entity);
    }
    this.redraw();
  }

  private releaseSurfaceMarkers(): void {
    for (const child of [...this.surfaceRoot.children]) child.destroy();
    for (const mesh of this.surfaceMeshes.splice(0)) mesh.destroy();
    for (const fill of this.surfaceMaterials.splice(0)) fill.destroy();
  }

  /** Active physics colliders are independent of selection frames and viewport Gaussian visibility. */
  setColliders(boxes: readonly OverlayBox[], visible: boolean, wire = false): void {
    if (!this.alive) return;
    this.colliderWire = wire;
    this.colliderRoot.enabled = visible;
    // Display toggles must preserve the pose currently supplied by the Walk simulation.
    if (this.colliderInputs === boxes) {
      this.colliderOutlines.forEach((outline, index) => {
        const fill = this.colliderMaterials[index];
        fill.opacity = wire ? 1 : 0.3;
        fill.blendType = wire ? BLEND_NONE : BLEND_NORMAL;
        fill.depthWrite = wire;
        fill.update();
        paint(outline.root, fill, wire);
      });
      this.redraw();
      return;
    }
    this.colliderInputs = boxes;
    for (const child of [...this.colliderRoot.children]) child.destroy();
    for (const fill of this.colliderMaterials.splice(0)) fill.destroy();
    this.colliderOutlines = boxes.map((box) => {
      const fill = material(themeColor("--studio-geometry", "#2f7ea8"), wire ? 1 : 0.3, false);
      this.colliderMaterials.push(fill);
      const root = new Entity(`r2s-collider-${box.id}`, this.app);
      root.setLocalPosition(...box.center);
      root.setLocalRotation(new Quat(...box.rotation_xyzw));
      this.colliderRoot.addChild(root);
      const outline: Outline = { localTransform: box.colliderLocalTransform, id: box.id, root, box: null, shape: null };
      const current = this.objects.get(box.id)?.entity;
      if (current) {
        const position = current.getLocalPosition();
        const rotation = current.getLocalRotation();
        this.setOutlinePose(outline, [position.x, position.y, position.z], [rotation.x, rotation.y, rotation.z, rotation.w]);
      }
      if (box.shapeUrl) {
        const record = this.shape(box.shapeUrl);
        if (record.geometry) this.showShape(outline, record, fill);
        else if (!record.failed) record.asset.once("load", () => {
          if (!this.alive || !this.colliderOutlines.includes(outline) || !record.geometry) return;
          this.showShape(outline, record, fill);
          this.redraw();
        });
      } else {
        const entity = new Entity(`r2s-collider-fill-${box.id}`, this.app);
        entity.addComponent("render", { type: "box", material: fill });
        entity.setLocalScale(...box.dimensions);
        paint(entity, fill, wire);
        root.addChild(entity);
        outline.box = entity;
      }
      return outline;
    });
    this.redraw();
  }

  /** Asset hình dáng theo URL, nạp một lần cho cả vòng đời lớp phủ (đổi lựa chọn không tải lại). */
  private shape(url: string): ShapeRecord {
    const existing = this.shapes.get(url);
    if (existing) return existing;
    const asset = new Asset(`r2s-shape-${url}`, "container", { url, filename: "shape.glb" });
    const record: ShapeRecord = { asset, geometry: null, failed: false };
    this.shapes.set(url, record);
    asset.once("load", () => {
      if (this.destroyed) return;
      record.geometry = shapeGeometry(asset.resource as ContainerResource);
      record.failed = record.geometry === null;
    });
    asset.once("error", () => {
      record.failed = true; // Selection keeps its box; do not render a substitute for failed collider geometry.
    });
    this.app.assets.add(asset);
    this.app.assets.load(asset);
    return record;
  }

  private showSelectionShape(outline: Outline, record: ShapeRecord, fill: StandardMaterial, emphasized: boolean): void {
    const container = record.asset.resource as ContainerResource;
    const solid = container.instantiateRenderEntity();
    paint(solid, fill, false);
    outline.root.addChild(solid);
    if (emphasized) {
      const edge = material(themeColor("--studio-on-dark", "#f5efe6"), 1, false);
      this.materials.push(edge);
      const wire = container.instantiateRenderEntity();
      paint(wire, edge, true);
      outline.root.addChild(wire);
    }
    outline.shape = record.geometry;
  }

  private showShape(outline: Outline, record: ShapeRecord, fill: StandardMaterial): void {
    const container = record.asset.resource as ContainerResource;
    const solid = container.instantiateRenderEntity();
    paint(solid, fill, this.colliderWire);
    outline.root.addChild(solid);
    outline.shape = record.geometry;
  }

  /**
   * Đồng bộ các vật có Gaussian riêng: thêm vật mới (nạp PLY một lần theo URL), gỡ vật đã mất, cập nhật
   * transform và ẩn/hiện. Entity của vật nằm dưới gốc Z-up nên toạ độ cục bộ chính là transform SceneIR.
   */
  setObjects(items: readonly OverlayObject[]): void {
    if (!this.alive) return;
    const wanted = new Set(items.map((item) => item.id));
    for (const [id, record] of this.objects) {
      if (wanted.has(id) && record.url === items.find((item) => item.id === id)?.url) continue;
      if (this.gizmo && this.gizmoTarget === id) this.detachGizmo();
      this.releaseObject(record);
      this.objects.delete(id);
    }
    for (const item of items) {
      let record = this.objects.get(item.id);
      if (!record) {
        const entity = new Entity(`r2s-object-${item.id}`, this.app);
        this.objectRoot.addChild(entity);
        record = { entity, asset: null, url: item.url };
        this.objects.set(item.id, record);
        if (item.url) {
          const model = item.kind === "model";
          const asset = model
            ? new Asset(`r2s-object-${item.id}`, "container", { url: item.url, filename: "asset.glb" })
            : new Asset(`r2s-object-${item.id}`, "gsplat", { url: item.url, filename: "object.ply" });
          record.asset = asset;
          asset.once("load", () => {
            if (this.destroyed || this.objects.get(item.id)?.asset !== asset) return;
            // GLB giữ màu đỉnh của asset; entity con bị huỷ cùng entity của vật khi gỡ.
            if (model) entity.addChild((asset.resource as ContainerResource).instantiateRenderEntity());
            else entity.addComponent("gsplat", { asset });
            this.redraw();
          });
          this.app.assets.add(asset);
          this.app.assets.load(asset);
        }
      }
      this.setObjectPose(item.id, item.position, item.rotation_xyzw);
      record.entity.enabled = item.visible;
    }
    this.redraw();
  }

  /** Đặt pose (hệ canonical, như SceneIR) cho một vật đang vẽ — dùng khi vật lý phía trình duyệt dời vật. */
  setObjectPose(id: string, position: Vec3, rotation_xyzw: [number, number, number, number]): void {
    const record = this.alive ? this.objects.get(id) : undefined;
    if (record) {
      record.entity.setLocalPosition(...position);
      record.entity.setLocalRotation(new Quat(...rotation_xyzw));
    }
    for (const outline of [...this.outlines, ...this.colliderOutlines]) {
      if (outline.id === id) this.setOutlinePose(outline, position, rotation_xyzw);
    }
    this.redraw();
  }

  private setOutlinePose(outline: Outline, position: Vec3, rotation: [number, number, number, number]): void {
    const local = outline.localTransform;
    const offset = local ? rotateVector(rotation, local.translation_xyz) : [0, 0, 0];
    outline.root.setLocalPosition(position[0] + offset[0], position[1] + offset[1], position[2] + offset[2]);
    outline.root.setLocalRotation(new Quat(...(local ? multiplyQuaternions(rotation, local.rotation_quaternion_xyzw) : rotation)));
  }

  private gizmoTarget: string | null = null;

  /** Gắn gizmo dịch/xoay vào một vật; `null` để gỡ. Kéo gizmo chỉ đổi entity, backend đổi khi `onEnd`. */
  attachGizmo(id: string | null, mode: GizmoMode, handlers: GizmoHandlers): void {
    this.detachGizmo();
    const target = id ? this.objects.get(id)?.entity : undefined;
    const camera = this.alive ? (this.app.root.findComponents("camera")[0] as CameraComponent | undefined) : undefined;
    if (!id || !target || !camera) return;
    this.gizmoLayer ??= Gizmo.createLayer(this.app);
    const gizmo = mode === "rotate" ? new RotateGizmo(camera, this.gizmoLayer) : new TranslateGizmo(camera, this.gizmoLayer);
    gizmo.coordSpace = "local";
    gizmo.attach([target]);
    gizmo.on("transform:start", () => handlers.onStart());
    gizmo.on("transform:move", () => {
      // Khung của vật đi theo trong lúc kéo để người dùng thấy collider sẽ nằm ở đâu.
      for (const outline of [...this.outlines, ...this.colliderOutlines]) {
        if (outline.id !== id) continue;
        const p = target.getLocalPosition();
        const q = target.getLocalRotation();
        this.setOutlinePose(outline, [p.x, p.y, p.z], [q.x, q.y, q.z, q.w]);
      }
      const p = target.getLocalPosition();
      const q = target.getLocalRotation();
      handlers.onMove?.(id, [p.x, p.y, p.z], [q.x, q.y, q.z, q.w]);
      this.redraw();
    });
    gizmo.on("transform:end", () => {
      const p = target.getLocalPosition();
      const q = target.getLocalRotation();
      handlers.onEnd(id, [p.x, p.y, p.z], [q.x, q.y, q.z, q.w]);
    });
    gizmo.on("render:update", () => this.redraw());
    this.gizmo = gizmo;
    this.gizmoTarget = id;

    const canvas = (gizmo as unknown as { _device?: { canvas?: HTMLCanvasElement } })._device?.canvas
      ?? (this.app as unknown as { graphicsDevice?: { canvas?: HTMLCanvasElement } }).graphicsDevice?.canvas;

    if (canvas) {
      const isolation = isolateGizmoPointer(gizmo, canvas);
      this.gizmoCleanup = () => isolation.dispose();
    }

    this.redraw();
  }

  /** App PlayCanvas còn dùng được: chưa `destroy()` và PlayCanvas chưa huỷ app. Lớp phủ con kiểm trước khi chạm scene. */
  isAlive(): boolean {
    return this.alive;
  }

  /** App PlayCanvas của viewer; chỉ gọi khi `isAlive()`. */
  application(): AppBase {
    return this.app;
  }

  /** Camera đang render của viewer, hoặc null khi app đã huỷ. */
  activeCamera(): CameraComponent | null {
    if (!this.alive) return null;
    return (this.app.root.findComponents("camera")[0] as CameraComponent | undefined) ?? null;
  }

  /** Entity gốc của một vật đang vẽ (đã mang pose hiện tại của vật); null nếu chưa có vật này. */
  objectEntity(id: string): Entity | null {
    return (this.alive ? this.objects.get(id)?.entity : undefined) ?? null;
  }

  /** Layer gizmo dùng chung, tạo khi cần. Mỗi gizmo thêm layer của nó vào camera nên không tạo layer riêng từng lớp. */
  sharedGizmoLayer(): Layer {
    this.gizmoLayer ??= Gizmo.createLayer(this.app);
    return this.gizmoLayer;
  }

  /** Yêu cầu render ở frame kế tiếp (viewer render theo yêu cầu). */
  requestFrame(): void {
    this.redraw();
  }

  /** Nối lệnh chuyển camera của viewer (`ViewerControls.gotoPose`); `null` để gỡ. */
  bindViewerGotoPose(goto: ((pose: DisplayCameraPose) => boolean) | null): void {
    this.viewerGotoPose = goto;
  }

  /** Đưa camera viewer tới một pose (hệ hiển thị). False khi chưa nối hoặc viewer chưa sẵn sàng. */
  gotoPose(pose: DisplayCameraPose): boolean {
    return this.alive && (this.viewerGotoPose?.(pose) ?? false);
  }

  detachGizmo(): void {
    this.gizmoCleanup?.();
    this.gizmoCleanup = null;
    this.gizmo?.detach();
    this.gizmo?.destroy();
    this.gizmo = null;
    this.gizmoTarget = null;
    this.redraw();
  }

  private releaseObject(record: { entity: Entity; asset: Asset | null }): void {
    record.entity.destroy();
    if (record.asset) {
      this.app.assets?.remove(record.asset);
      record.asset.unload();
    }
  }

  private ghost: Entity | null = null;
  private ghostMaterial: StandardMaterial | null = null;

  /**
   * Giao tia chuột với sàn canonical (z = 0, hệ Z-up mét). `x`, `y` là CSS pixel tính từ góc trên-trái canvas.
   * Trả toạ độ [x, y, 0] trên sàn, hoặc null nếu tia không chạm sàn phía trước camera.
   */
  floorPoint(x: number, y: number): Vec3 | null {
    if (!this.alive) return null;
    const camera = this.app.root.findComponents("camera")[0] as CameraComponent | undefined;
    if (!camera) return null;
    const inverse = this.root.getWorldTransform().clone().invert();
    const originWorld = camera.entity.getPosition().clone();
    const farWorld = camera.screenToWorld(x, y, camera.farClip, new PcVec3());
    const o = inverse.transformPoint(originWorld, new PcVec3());
    const f = inverse.transformPoint(farWorld, new PcVec3());
    const dz = f.z - o.z;
    if (Math.abs(dz) < 1e-9) return null;
    const t = -o.z / dz;
    if (t <= 0 || t > 1) return null;
    return [o.x + (f.x - o.x) * t, o.y + (f.y - o.y) * t, 0];
  }

  /** Hộp xem trước khi đặt vật bằng chuột: đáy nằm trên sàn tại `position`; `null` để ẩn. */
  setGhost(dimensions: Vec3 | null, position: Vec3 | null = null): void {
    if (!this.alive) return;
    if (!dimensions || !position) {
      if (this.ghost) this.ghost.enabled = false;
      this.redraw();
      return;
    }
    if (!this.ghost) {
      this.ghostMaterial = material(themeColor("--studio-ember", "#e8743b"), 0.45, false);
      this.ghost = new Entity("r2s-ghost", this.app);
      this.ghost.addComponent("render", { type: "box", material: this.ghostMaterial });
      this.root.addChild(this.ghost);
    }
    this.ghost.enabled = true;
    this.ghost.setLocalScale(dimensions[0], dimensions[1], dimensions[2]);
    this.ghost.setLocalPosition(position[0], position[1], position[2] + dimensions[2] / 2);
    this.redraw();
  }

  /**
   * Vật gần nhất dưới con trỏ. `x`, `y` là toạ độ CSS pixel tính từ góc trên-trái canvas (quy ước
   * `CameraComponent.screenToWorld`). Chỉ xét khung đang vẽ; vật đã có hình dáng thì thử theo lưới
   * của nó (bấm vào khoảng trống trong hộp bao không chọn vật), còn lại thử theo hộp.
   */
  /** Pick a rendered environment triangle in canonical coordinates for a user-authored plane. */
  pickCollisionTriangle(x: number, y: number, expectedUrl?: string): [Vec3, Vec3, Vec3] | null {
    if (!this.alive || !this.collisionGeometry || (expectedUrl && this.collisionGeometryUrl !== expectedUrl)) return null;
    const camera = this.app.root.findComponents("camera")[0] as CameraComponent | undefined;
    if (!camera) return null;
    const worldOrigin = camera.entity.getPosition().clone();
    const worldDirection = camera.screenToWorld(x, y, camera.farClip, new PcVec3()).sub(worldOrigin).normalize();
    const inverse = this.root.getWorldTransform().clone().invert();
    const origin = inverse.transformPoint(worldOrigin, new PcVec3());
    const direction = inverse.transformVector(worldDirection, new PcVec3());
    const {positions,indices} = this.collisionGeometry;
    let best = -1, nearest = Infinity;
    for (let i = 0; i < indices.length; i += 3) {
      const hit = rayTriangles([origin.x,origin.y,origin.z], [direction.x,direction.y,direction.z], positions, indices.subarray(i,i+3));
      if (hit !== null && hit < nearest) {nearest=hit;best=i;}
    }
    if (best < 0) return null;
    return [0,1,2].map(corner => {
      const index = indices[best+corner]*3;
      return [positions[index],positions[index+1],positions[index+2]] as Vec3;
    }) as [Vec3,Vec3,Vec3];
  }

  pick(x: number, y: number): string | null {
    if (!this.alive) return null;
    const camera = this.app.root.findComponents("camera")[0] as CameraComponent | undefined;
    if (!camera) return null;
    const origin = camera.entity.getPosition().clone();
    const direction = camera.screenToWorld(x, y, camera.farClip, new PcVec3()).sub(origin).normalize();
    let best: string | null = null;
    let nearest = Infinity;
    for (const outline of this.outlines) {
      const entity = outline.shape ? outline.root : outline.box;
      if (!entity) continue;
      const inverse = entity.getWorldTransform().clone().invert();
      const o = inverse.transformPoint(origin, new PcVec3());
      const d = inverse.transformVector(direction, new PcVec3());
      const hit = outline.shape
        ? rayTriangles([o.x, o.y, o.z], [d.x, d.y, d.z], outline.shape.positions, outline.shape.indices)
        : rayUnitBox([o.x, o.y, o.z], [d.x, d.y, d.z]);
      if (hit !== null && hit < nearest) {
        nearest = hit;
        best = outline.id;
      }
    }
    return best;
  }

  destroy(): void {
    this.detachGizmo();
    this.destroyed = true;
    this.ghostMaterial?.destroy();
    this.ghostMaterial = null;
    this.ghost = null;
    for (const record of this.objects.values()) this.releaseObject(record);
    this.objects.clear();
    this.outlines = [];
    this.colliderOutlines = [];
    for (const fill of this.colliderMaterials.splice(0)) fill.destroy();
    this.releasePoints();
    this.releaseSurfaceMarkers();
    this.releaseCollision();
    this.root.destroy();
    for (const record of this.shapes.values()) {
      this.app.assets?.remove(record.asset);
      record.asset.unload();
    }
    this.shapes.clear();
    this.releaseMaterials();
  }

  /**
   * Viewer render theo yêu cầu (tắt `autoRender` sau frame đầu, chỉ vẽ lại khi camera đổi):
   * đổi lớp phủ mà không xin frame mới thì màn hình giữ nguyên tới lần xoay camera kế tiếp.
   */
  private redraw(): void {
    if (this.alive) this.app.renderNextFrame = true;
  }

  private releaseMaterials(): void {
    for (const item of this.materials.splice(0)) item.destroy();
  }
}
