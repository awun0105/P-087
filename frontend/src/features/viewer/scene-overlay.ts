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
  Quat,
  StandardMaterial,
  Vec3 as PcVec3,
  type AppBase,
  type CameraComponent,
  type ContainerResource,
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

export class SceneOverlay {
  private readonly app: AppBase;
  private readonly root: Entity;
  private readonly boxRoot: Entity;
  private readonly materials: StandardMaterial[] = [];
  private collisionAsset: Asset | null = null;
  private collisionEntity: Entity | null = null;
  private collisionMaterial: StandardMaterial | null = null;
  private readonly boxIds = new Map<Entity, string>();
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
    this.destroyed = true;
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
