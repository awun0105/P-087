/**
 * Góc nhìn thứ ba cho chế độ đi bộ của viewer (kế hoạch scene tương tác, H4).
 *
 * Thư viện viewer tự điều khiển camera ở tầm mắt người đi (góc nhìn thứ nhất) và tự xử lý va chạm. Lớp này không
 * thay bộ điều khiển đó: ngay trước khi vẽ mỗi frame, nó đặt một hình người tại chỗ người đi đang đứng rồi lùi
 * camera ra sau lưng; vẽ xong thì trả camera về chỗ cũ, nên trạng thái của thư viện không bị đổi.
 *
 * Camera lùi tới đâu bị lưới va chạm chặn tới đó (không nhìn xuyên tường). Hình người hiện là hình khối dựng sẵn
 * trong code — chưa dùng asset nhân vật nào (việc chọn asset và giấy phép là quyết định riêng của owner).
 */

import { Color, Entity, StandardMaterial, Vec3 as PcVec3, type AppBase } from "playcanvas";

import type { Vec3 } from "@/features/viewer/source-frame";
import { themeColor } from "@/lib/theme";

export interface ThirdPersonOptions {
  /** Camera lùi ra sau lưng bao xa (mét). */
  distance: number;
  /** Camera nâng lên so với tầm mắt (mét). */
  lift: number;
  /** Khoảng hở giữ lại trước vật cản (mét). */
  margin: number;
  /** Bước dò vật cản dọc đường lùi (mét). */
  step: number;
}

export const THIRD_PERSON_DEFAULTS: ThirdPersonOptions = { distance: 2.4, lift: 0.35, margin: 0.25, step: 0.1 };

/** Tầm mắt của người đi trong thư viện viewer (mét trên sàn); hình người được dựng theo chiều cao này. */
export const WALK_EYE_HEIGHT_M = 1.3;

/** Ô lưới va chạm (mét); đủ nhỏ để tường mỏng vẫn chặn camera, đủ lớn để tra nhanh. */
export const OCCUPANCY_CELL_M = 0.15;

function cellKey(x: number, y: number, z: number, cell: number): string {
  return `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`;
}

/** Tập ô có đỉnh của lưới va chạm; `positions` là xyz liên tiếp trong không gian hiển thị. */
export function buildOccupancy(positions: ArrayLike<number>, cell = OCCUPANCY_CELL_M): Set<string> {
  const occupied = new Set<string>();
  for (let i = 0; i + 2 < positions.length; i += 3) occupied.add(cellKey(positions[i], positions[i + 1], positions[i + 2], cell));
  return occupied;
}

export function occupancyTest(occupied: Set<string>, cell = OCCUPANCY_CELL_M): (point: Vec3) => boolean {
  return ([x, y, z]) => occupied.has(cellKey(x, y, z, cell));
}

/**
 * Vị trí camera góc nhìn thứ ba trong không gian hiển thị (trục Y hướng lên): lùi sau lưng theo hướng nhìn đã
 * chiếu xuống mặt ngang, nâng lên một chút; dừng trước vật cản đầu tiên trên đường lùi.
 * Nhìn thẳng lên/xuống (không còn hướng ngang) thì giữ nguyên tầm mắt, chỉ nâng camera.
 */
export function thirdPersonCameraPosition(
  eye: Vec3,
  forward: Vec3,
  options: ThirdPersonOptions = THIRD_PERSON_DEFAULTS,
  occupied: (point: Vec3) => boolean = () => false,
): Vec3 {
  const flat = Math.hypot(forward[0], forward[2]);
  if (flat < 1e-6) return [eye[0], eye[1] + options.lift, eye[2]];
  const back: Vec3 = [-forward[0] / flat, 0, -forward[2] / flat];
  let reach = options.distance;
  for (let travelled = options.step; travelled <= options.distance + 1e-9; travelled += options.step) {
    const fraction = travelled / options.distance;
    const probe: Vec3 = [eye[0] + back[0] * travelled, eye[1] + options.lift * fraction, eye[2] + back[2] * travelled];
    if (occupied(probe)) {
      reach = Math.max(0, travelled - options.step - options.margin);
      break;
    }
  }
  const fraction = reach / options.distance;
  return [eye[0] + back[0] * reach, eye[1] + options.lift * fraction, eye[2] + back[2] * reach];
}

type CameraEntity = Entity & { forward: PcVec3 };

/** Hình người và camera sau lưng, sống cùng app của viewer; `destroy()` gỡ listener và giải phóng entity/material. */
export class ThirdPersonRig {
  private readonly app: AppBase;
  private readonly avatar: Entity;
  private readonly material: StandardMaterial;
  private readonly saved = new PcVec3();
  private moved = false;
  private active = false;
  private occupied: (point: Vec3) => boolean = () => false;

  constructor(app: AppBase, private readonly options: ThirdPersonOptions = THIRD_PERSON_DEFAULTS) {
    this.app = app;
    this.material = new StandardMaterial();
    this.material.diffuse = new Color().fromString(themeColor("--studio-marker-b", "#ffb333"));
    this.material.update();
    this.avatar = new Entity("r2s-avatar", app);
    const body = new Entity("r2s-avatar-body", app);
    body.addComponent("render", { type: "capsule", material: this.material, castShadows: false });
    // Capsule mặc định cao 2, bán kính 0,5: thu về thân người cao tới vai, đặt chân tại gốc.
    const bodyHeight = WALK_EYE_HEIGHT_M - 0.15;
    body.setLocalScale(0.45, bodyHeight / 2, 0.45);
    body.setLocalPosition(0, bodyHeight / 2, 0);
    const head = new Entity("r2s-avatar-head", app);
    head.addComponent("render", { type: "sphere", material: this.material, castShadows: false });
    head.setLocalScale(0.26, 0.26, 0.26);
    head.setLocalPosition(0, WALK_EYE_HEIGHT_M, 0);
    this.avatar.addChild(body);
    this.avatar.addChild(head);
    this.avatar.enabled = false;
    app.root.addChild(this.avatar);
    app.on("prerender", this.before, this);
    app.on("postrender", this.after, this);
  }

  /** Lưới va chạm (đỉnh trong không gian hiển thị) để camera không lùi xuyên tường; null = không chặn. */
  setCollision(positions: ArrayLike<number> | null): void {
    this.occupied = positions ? occupancyTest(buildOccupancy(positions)) : () => false;
  }

  /** Bật khi đang ở chế độ đi bộ và người dùng chọn góc nhìn thứ ba. */
  setActive(active: boolean): void {
    this.active = active;
    if (!active) this.avatar.enabled = false;
    if (this.app.root) this.app.renderNextFrame = true;
  }

  private camera(): CameraEntity | null {
    const component = this.app.root?.findComponent("camera") as { entity: CameraEntity } | null;
    return component?.entity ?? null;
  }

  private before(): void {
    const camera = this.active ? this.camera() : null;
    if (!camera) return;
    const eye = camera.getPosition();
    const forward = camera.forward;
    this.saved.copy(eye);
    this.avatar.enabled = true;
    this.avatar.setPosition(eye.x, eye.y - WALK_EYE_HEIGHT_M, eye.z);
    this.avatar.setEulerAngles(0, (Math.atan2(-forward.x, -forward.z) * 180) / Math.PI, 0);
    const [x, y, z] = thirdPersonCameraPosition([eye.x, eye.y, eye.z], [forward.x, forward.y, forward.z], this.options, this.occupied);
    camera.setPosition(x, y, z);
    this.moved = true;
  }

  private after(): void {
    if (!this.moved) return;
    this.moved = false;
    this.camera()?.setPosition(this.saved);
  }

  destroy(): void {
    this.after();
    this.app.off("prerender", this.before, this);
    this.app.off("postrender", this.after, this);
    this.avatar.destroy();
    this.material.destroy();
  }
}
