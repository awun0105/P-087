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
  Quat,
  RENDERSTYLE_WIREFRAME,
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

import { DISPLAY_EULER, type Vec3 } from "@/features/viewer/source-frame";
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

export interface OverlayBox {
  id: string;
  center: Vec3;
  rotation_xyzw: [number, number, number, number];
  dimensions: Vec3;
  /** Màu hex, vd `#22c55e`. */
  color: string;
  emphasized: boolean;
  /**
   * GLB hình dáng của vật trong khung cục bộ của vật (collider phân rã lồi). Có thì vật được vẽ và
   * bắt chọn theo đúng hình này; hộp chỉ hiện trong lúc GLB đang tải hoặc khi tải lỗi.
   */
  shapeUrl?: string | null;
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
      if (wire) {
        instance.mesh.generateWireframe();
        instance.renderStyle = RENDERSTYLE_WIREFRAME;
      }
    }
  }
}

/**
 * Gộp mọi mesh của GLB thành một lưới trong khung gốc của GLB (đã áp transform của node), để tia
 * chọn vật thử trên đúng hình đang vẽ. Null khi GLB không có tam giác.
 */
function shapeGeometry(container: ContainerResource): ShapeGeometry | null {
  const entity = container.instantiateRenderEntity();
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
  entity.destroy();
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
  onStart(): void;
  /** Transform cục bộ của vật (hệ canonical Z-up, mét) khi người dùng thả gizmo. */
  onEnd(id: string, position: Vec3, rotation_xyzw: [number, number, number, number]): void;
}

export class SceneOverlay {
  private readonly app: AppBase;
  private readonly root: Entity;
  private readonly boxRoot: Entity;
  private readonly materials: StandardMaterial[] = [];
  private collisionAsset: Asset | null = null;
  private collisionEntity: Entity | null = null;
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
    return new Promise((resolve, reject) => {
      const asset = new Asset(`r2s-collision-${url}`, "container", { url });
      this.collisionAsset = asset;
      asset.once("load", () => {
        if (this.destroyed) return resolve(0);
        const entity = (asset.resource as ContainerResource).instantiateRenderEntity();
        this.collisionMaterial = material(themeColor("--studio-geometry", "#2f7ea8"), opacity, true);
        let triangles = 0;
        for (const render of entity.findComponents("render") as unknown as { meshInstances: { material: unknown; mesh: { primitive: { count: number }[] } }[] }[]) {
          for (const instance of render.meshInstances) {
            instance.material = this.collisionMaterial;
            triangles += (instance.mesh.primitive[0]?.count ?? 0) / 3;
          }
        }
        this.collisionEntity = entity;
        this.root.addChild(entity);
        this.redraw();
        resolve(triangles);
      });
      asset.once("error", (error: unknown) => reject(new Error(String(error))));
      this.app.assets.add(asset);
      this.app.assets.load(asset);
    });
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

  setCollision(visible: boolean, opacity: number): void {
    if (!this.alive) return;
    if (this.collisionEntity) this.collisionEntity.enabled = visible;
    const current = this.collisionMaterial;
    if (!current) return this.redraw();
    current.opacity = opacity;
    current.blendType = opacity < 1 ? BLEND_NORMAL : BLEND_NONE;
    current.depthWrite = opacity >= 1;
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
   * Vẽ lại khung của mọi vật; vật được nhấn mạnh đậm hơn và có thêm nét viền. Vật có `shapeUrl` hiện
   * theo đúng hình dáng (collider) của nó, hộp chỉ là hình lùi trong lúc chờ tải.
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
      const outline: Outline = { id: box.id, root, box: null, shape: null };
      const record = box.shapeUrl ? this.shape(box.shapeUrl) : null;
      if (record?.geometry) {
        this.showShape(outline, record, fill, box.emphasized);
      } else {
        const fallback = new Entity(`r2s-box-fill-${box.id}`, this.app);
        fallback.addComponent("render", { type: "box", material: fill });
        fallback.setLocalScale(...box.dimensions);
        root.addChild(fallback);
        outline.box = fallback;
        if (record && !record.failed) {
          record.asset.once("load", () => {
            // Chỉ thay khi khung này vẫn là khung đang vẽ (setBoxes sau đó đã tạo lại thì bỏ qua).
            if (!this.alive || !this.outlines.includes(outline) || !record.geometry) return;
            fallback.destroy();
            outline.box = null;
            this.showShape(outline, record, fill, box.emphasized);
            this.redraw();
          });
        }
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
      record.failed = true; // Giữ hộp lùi; không làm hỏng lớp phủ vì một collider tải lỗi.
    });
    this.app.assets.add(asset);
    this.app.assets.load(asset);
    return record;
  }

  private showShape(outline: Outline, record: ShapeRecord, fill: StandardMaterial, emphasized: boolean): void {
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
      record.entity.setLocalPosition(...item.position);
      record.entity.setLocalRotation(new Quat(...item.rotation_xyzw));
      record.entity.enabled = item.visible;
    }
    this.redraw();
  }

  /** Đặt pose (hệ canonical, như SceneIR) cho một vật đang vẽ — dùng khi vật lý phía trình duyệt dời vật. */
  setObjectPose(id: string, position: Vec3, rotation_xyzw: [number, number, number, number]): void {
    const record = this.alive ? this.objects.get(id) : undefined;
    if (!record) return;
    record.entity.setLocalPosition(...position);
    record.entity.setLocalRotation(new Quat(...rotation_xyzw));
    const outline = this.outlines.find((item) => item.id === id);
    if (outline) {
      outline.root.setLocalPosition(...position);
      outline.root.setLocalRotation(new Quat(...rotation_xyzw));
    }
    this.redraw();
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
      for (const outline of this.outlines) {
        if (outline.id !== id) continue;
        outline.root.setLocalPosition(target.getLocalPosition());
        outline.root.setLocalRotation(target.getLocalRotation());
      }
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

    // Cô lập cử chỉ kéo của Gizmo khỏi Camera Controller của supersplat-viewer:
    // Mặc định PlayCanvas Gizmo nghe `pointerdown` ở pha bubbling trên canvas. Cùng lúc đó,
    // KeyboardMouseSource của supersplat cũng nhận sự kiện và ghi nhận dịch chuyển chuột làm xoay/di
    // chuyển camera.
    // Bằng cách gỡ listener bubble mặc định và chặn ở pha CAPTURE:
    // - Khi người dùng bấm trúng trục/mặt điều khiển của Gizmo: gọi `stopImmediatePropagation()` để
    //   Camera Controller hoàn toàn không thấy sự kiện bắt đầu kéo, chỉ Gizmo xử lý biến đổi vật.
    // - Khi bấm ngoài Gizmo: sự kiện lan truyền bình thường để xoay camera hoặc chọn vật.
    const canvas = (gizmo as unknown as { _device?: { canvas?: HTMLCanvasElement } })._device?.canvas
      ?? (this.app as unknown as { graphicsDevice?: { canvas?: HTMLCanvasElement } }).graphicsDevice?.canvas;

    if (canvas) {
      type GizmoInternal = {
        _onPointerDown: (e: PointerEvent) => void;
        _onPointerMove: (e: PointerEvent) => void;
        _onPointerUp: (e: PointerEvent) => void;
        _getSelection: (x: number, y: number) => unknown[];
      };
      const gizmoInternal = gizmo as unknown as GizmoInternal;
      canvas.removeEventListener("pointerdown", gizmoInternal._onPointerDown);
      canvas.removeEventListener("pointermove", gizmoInternal._onPointerMove);
      canvas.removeEventListener("pointerup", gizmoInternal._onPointerUp);

      let dragging = false;
      let activePointerId: number | null = null;

      const onCapturePointerDown = (e: PointerEvent) => {
        if (e.target !== canvas || !gizmo.enabled) return;
        if (typeof document !== "undefined" && document.pointerLockElement) return;
        if (e.button !== 0) return;

        const selection = gizmoInternal._getSelection?.(e.offsetX, e.offsetY);
        if (selection && selection.length > 0) {
          dragging = true;
          activePointerId = e.pointerId;
          e.stopImmediatePropagation();
          e.preventDefault();
          gizmoInternal._onPointerDown(e);
        }
      };

      const onCapturePointerMove = (e: PointerEvent) => {
        if (dragging && e.pointerId === activePointerId) {
          e.stopImmediatePropagation();
          e.preventDefault();
          gizmoInternal._onPointerMove(e);
        } else if (!dragging) {
          gizmoInternal._onPointerMove(e);
        }
      };

      const onCapturePointerUp = (e: PointerEvent) => {
        if (dragging && (activePointerId === null || e.pointerId === activePointerId)) {
          dragging = false;
          activePointerId = null;
          e.stopImmediatePropagation();
          e.preventDefault();
          gizmoInternal._onPointerUp(e);
        }
      };

      const onLostPointerCapture = (e: PointerEvent) => {
        if (dragging && (activePointerId === null || e.pointerId === activePointerId)) {
          dragging = false;
          activePointerId = null;
          gizmoInternal._onPointerUp(e);
        }
      };

      canvas.addEventListener("pointerdown", onCapturePointerDown, { capture: true });
      canvas.addEventListener("pointermove", onCapturePointerMove, { capture: true });
      canvas.addEventListener("pointerup", onCapturePointerUp, { capture: true });
      canvas.addEventListener("pointercancel", onCapturePointerUp, { capture: true });
      canvas.addEventListener("lostpointercapture", onLostPointerCapture);

      this.gizmoCleanup = () => {
        if (activePointerId !== null) {
          try {
            if (canvas.hasPointerCapture?.(activePointerId)) {
              canvas.releasePointerCapture(activePointerId);
            }
          } catch {
            // Không lỗi nếu browser đã giải phóng trước
          }
        }
        canvas.removeEventListener("pointerdown", onCapturePointerDown, { capture: true });
        canvas.removeEventListener("pointermove", onCapturePointerMove, { capture: true });
        canvas.removeEventListener("pointerup", onCapturePointerUp, { capture: true });
        canvas.removeEventListener("pointercancel", onCapturePointerUp, { capture: true });
        canvas.removeEventListener("lostpointercapture", onLostPointerCapture);
      };
    }

    this.redraw();
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
    this.releasePoints();
    this.root.destroy();
    for (const record of this.shapes.values()) {
      this.app.assets?.remove(record.asset);
      record.asset.unload();
    }
    this.shapes.clear();
    this.releaseMaterials();
    this.collisionMaterial?.destroy();
    if (this.collisionAsset) {
      this.app.assets?.remove(this.collisionAsset);
      this.collisionAsset.unload();
    }
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
