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
  Quat,
  RotateGizmo,
  StandardMaterial,
  TranslateGizmo,
  Vec3 as PcVec3,
  type AppBase,
  type CameraComponent,
  type ContainerResource,
  type Layer,
} from "playcanvas";

import { DISPLAY_EULER, type Vec3 } from "@/features/viewer/source-frame";
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

export interface OverlayBox {
  id: string;
  center: Vec3;
  rotation_xyzw: [number, number, number, number];
  dimensions: Vec3;
  /** Màu hex, vd `#22c55e`. */
  color: string;
  emphasized: boolean;
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
  /** URL file PLY Gaussian của vật; null với vật không có hình riêng (vật cản hộp, asset). */
  url: string | null;
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
  private readonly boxIds = new Map<Entity, string>();
  private readonly objectRoot: Entity;
  private readonly objects = new Map<string, { entity: Entity; asset: Asset | null; url: string | null }>();
  private gizmoLayer: Layer | null = null;
  private gizmo: TranslateGizmo | RotateGizmo | null = null;
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
        this.collisionMaterial = material("#8aa4c8", opacity, true);
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

  /** Vẽ lại toàn bộ hộp; hộp được nhấn mạnh đậm hơn. */
  setBoxes(boxes: readonly OverlayBox[]): void {
    if (!this.alive) return;
    for (const child of [...this.boxRoot.children]) child.destroy();
    this.boxIds.clear();
    this.releaseMaterials();
    for (const box of boxes) {
      const fill = material(box.color, box.emphasized ? 0.55 : 0.28, false);
      this.materials.push(fill);
      const entity = new Entity(`r2s-box-${box.id}`, this.app);
      entity.addComponent("render", { type: "box", material: fill });
      entity.setLocalPosition(...box.center);
      entity.setLocalRotation(new Quat(...box.rotation_xyzw));
      entity.setLocalScale(...box.dimensions);
      this.boxRoot.addChild(entity);
      this.boxIds.set(entity, box.id);
    }
    this.redraw();
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
          const asset = new Asset(`r2s-object-${item.id}`, "gsplat", { url: item.url, filename: "object.ply" });
          record.asset = asset;
          asset.once("load", () => {
            if (this.destroyed || this.objects.get(item.id)?.asset !== asset) return;
            entity.addComponent("gsplat", { asset });
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
      // Hộp của vật đi theo trong lúc kéo để người dùng thấy collider sẽ nằm ở đâu.
      for (const [box, boxId] of this.boxIds) {
        if (boxId !== id) continue;
        box.setLocalPosition(target.getLocalPosition());
        box.setLocalRotation(target.getLocalRotation());
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
    this.redraw();
  }

  detachGizmo(): void {
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

  /**
   * Hộp gần nhất dưới con trỏ. `x`, `y` là toạ độ CSS pixel tính từ góc trên-trái canvas (quy ước
   * `CameraComponent.screenToWorld`). Chỉ xét hộp đang vẽ.
   */
  pick(x: number, y: number): string | null {
    if (!this.alive) return null;
    const camera = this.app.root.findComponents("camera")[0] as CameraComponent | undefined;
    if (!camera) return null;
    const origin = camera.entity.getPosition().clone();
    const direction = camera.screenToWorld(x, y, camera.farClip, new PcVec3()).sub(origin).normalize();
    let best: string | null = null;
    let nearest = Infinity;
    for (const [entity, id] of this.boxIds) {
      const inverse = entity.getWorldTransform().clone().invert();
      const o = inverse.transformPoint(origin, new PcVec3());
      const d = inverse.transformVector(direction, new PcVec3());
      const hit = rayUnitBox([o.x, o.y, o.z], [d.x, d.y, d.z]);
      if (hit !== null && hit < nearest) {
        nearest = hit;
        best = id;
      }
    }
    return best;
  }

  destroy(): void {
    this.detachGizmo();
    this.destroyed = true;
    for (const record of this.objects.values()) this.releaseObject(record);
    this.objects.clear();
    this.boxIds.clear();
    this.root.destroy();
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
