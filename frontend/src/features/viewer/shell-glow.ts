/**
 * Vỏ phát sáng của vật trong Draft (T-017): vỏ thô của vật ôm sát Gaussian. Mỗi vật có tối đa một vỏ; vỏ là con của
 * entity vật nên đi theo transform của vật. Vật liệu phát sáng cộng dồn, không ghi depth, nên Gaussian bên trong vẫn
 * nhìn thấy được.
 */
import {
  Asset,
  BLEND_ADDITIVE,
  Color,
  CULLFACE_NONE,
  Entity,
  Mesh,
  MeshInstance,
  PRIMITIVE_POINTS,
  RENDERSTYLE_SOLID,
  RENDERSTYLE_WIREFRAME,
  StandardMaterial,
  type ContainerResource,
} from "playcanvas";

import type { SceneOverlay } from "@/features/viewer/scene-overlay";
import { themeColor } from "@/lib/theme";

export type ShellStyle = "selected" | "idle";

/** `pending`: đang tính xem trước, giữ vỏ cũ và làm mờ tới khi vỏ mới về; `warning`: xem trước lỗi, giữ vỏ và đổi màu cam. */
export type ShellTone = "normal" | "pending" | "warning";

/** Một vỏ cần vẽ: GLB theo URL; `selected` là vật đang chọn (sáng hơn, có viền). */
export interface ShellSpec {
  id: string;
  url: string;
  style: ShellStyle;
}

const SHELL_OPACITY: Record<ShellStyle, number> = { selected: 0.25, idle: 0.1 };
const WIRE_OPACITY = 0.5;
const PENDING_OPACITY = 0.12;
const PULSE_PERIOD_MS = 2000;
const PULSE_AMPLITUDE = 0.03;

interface PointRecord {
  root: Entity;
  meshes: Mesh[];
  materials: StandardMaterial[];
}

interface ShellRecord {
  style: ShellStyle;
  tone: ShellTone;
  /** Đang bị nhấp nháy: cần đặt lại độ mờ về gốc khi người dùng bật giảm chuyển động. */
  pulsing: boolean;
  root: Entity;
  fill: StandardMaterial;
  wire: StandardMaterial | null;
  asset: Asset;
  blobUrl: string | null;
  /** Hoàn tất lời hứa của `setShell` khi vỏ bị thay hoặc gỡ trước khi nạp xong. */
  settle: () => void;
}

type RenderLike = { meshInstances: MeshInstance[] };

/** Vật liệu điểm: màu phát sáng đặc, không ghi depth và luôn vẽ trên cùng để thấy được qua vỏ và Gaussian. */
function pointMaterial(hex: string): StandardMaterial {
  const result = new StandardMaterial();
  result.diffuse = new Color(0, 0, 0);
  result.emissive = new Color().fromString(hex);
  result.useLighting = false;
  result.depthTest = false;
  result.depthWrite = false;
  result.cull = CULLFACE_NONE;
  result.update();
  return result;
}

/** Vật liệu vỏ: màu phát sáng, không đổ bóng, cộng dồn, không ghi depth, hai mặt. Cùng kiểu với `material` của scene-overlay. */
function shellMaterial(hex: string, opacity: number): StandardMaterial {
  const result = new StandardMaterial();
  result.diffuse = new Color(0, 0, 0);
  result.emissive = new Color().fromString(hex);
  result.useLighting = false;
  result.opacity = opacity;
  result.blendType = BLEND_ADDITIVE;
  result.depthWrite = false;
  result.cull = CULLFACE_NONE;
  result.update();
  return result;
}

/** Gán vật liệu cho mọi mesh của một entity GLB; `wire` vẽ nét cạnh thay cho mặt (cùng cách với scene-overlay). */
function paint(entity: Entity, fill: StandardMaterial, wire: boolean): void {
  for (const render of entity.findComponents("render") as unknown as RenderLike[]) {
    for (const instance of render.meshInstances) {
      instance.material = fill;
      if (wire && !instance.mesh.primitive[RENDERSTYLE_WIREFRAME]) instance.mesh.generateWireframe();
      instance.renderStyle = wire ? RENDERSTYLE_WIREFRAME : RENDERSTYLE_SOLID;
    }
  }
}

/** Người dùng bật "giảm chuyển động" thì vỏ không nhấp nháy. */
function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** GLB của vỏ từ chuỗi base64 trong lần xem trước (máy chủ trả `shell_glb_base64`). */
export function decodeShellGlb(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

/** Lớp vỏ phát sáng của một viewer. Gắn vào `SceneOverlay`: vỏ được vẽ dưới entity của từng vật. */
export class ShellGlowLayer {
  private readonly shells = new Map<string, ShellRecord>();
  private readonly points = new Map<string, PointRecord>();
  private destroyed = false;
  private subscribed = false;

  constructor(private readonly host: SceneOverlay) {}

  /** Nhịp của vỏ đang chọn: độ mờ 0,22–0,28 theo chu kỳ 2 s; tắt khi người dùng bật giảm chuyển động. */
  private readonly onUpdate = (): void => {
    if (this.destroyed) return;
    const reduce = prefersReducedMotion();
    const wave = (1 - Math.cos((2 * Math.PI * performance.now()) / PULSE_PERIOD_MS)) / 2;
    let animating = false;
    for (const record of this.shells.values()) {
      if (record.style !== "selected" || record.tone !== "normal") continue;
      if (reduce) {
        if (record.pulsing) this.applyTone(record);
        continue;
      }
      record.pulsing = true;
      animating = true;
      record.fill.opacity = SHELL_OPACITY.selected + PULSE_AMPLITUDE * (2 * wave - 1);
      record.fill.emissiveIntensity = 1 + 0.3 * wave;
      record.fill.update();
    }
    if (animating) this.host.requestFrame();
  };

  /**
   * Vẽ vỏ của một vật (GLB dạng ArrayBuffer hoặc URL) làm con của entity vật; vỏ cũ của cùng vật được thay. Vật chưa có
   * entity trong viewer thì không vẽ gì. Promise hoàn tất khi vỏ đã gắn, hoặc khi vỏ đã bị thay/gỡ trước khi nạp xong.
   */
  setShell(objectId: string, glb: ArrayBuffer | string, style: ShellStyle): Promise<void> {
    const parent = this.parentOf(objectId);
    if (!parent) return Promise.resolve();
    this.releaseShell(objectId);
    const app = this.host.application();
    const url = typeof glb === "string" ? glb : URL.createObjectURL(new Blob([glb], { type: "model/gltf-binary" }));
    const blobUrl = typeof glb === "string" ? null : url;
    const asset = new Asset(`r2s-shell-${objectId}`, "container", { url, filename: "shell.glb" });
    return new Promise<void>((resolve, reject) => {
      const record: ShellRecord = {
        style,
        tone: "normal",
        pulsing: false,
        root: new Entity(`r2s-shell-${objectId}`, app),
        fill: shellMaterial(themeColor("--studio-sage", "#2dd4bf"), SHELL_OPACITY[style]),
        wire: style === "selected" ? shellMaterial(themeColor("--studio-sage", "#2dd4bf"), WIRE_OPACITY) : null,
        asset,
        blobUrl,
        settle: resolve,
      };
      parent.addChild(record.root);
      this.shells.set(objectId, record);
      this.subscribe();
      asset.once("load", () => {
        this.revoke(record);
        if (this.shells.get(objectId) !== record) return resolve();
        const container = asset.resource as ContainerResource;
        const solid = container.instantiateRenderEntity();
        paint(solid, record.fill, false);
        record.root.addChild(solid);
        if (record.wire) {
          const outline = container.instantiateRenderEntity();
          paint(outline, record.wire, true);
          record.root.addChild(outline);
        }
        resolve();
      });
      asset.once("error", () => {
        this.revoke(record);
        if (this.shells.get(objectId) === record) this.releaseShell(objectId);
        reject(new Error(`Không nạp được vỏ của vật ${objectId}`));
      });
      app.assets.add(asset);
      app.assets.load(asset);
    });
  }

  /**
   * Điểm của lần xem trước: `added` là Gaussian sẽ thêm (xanh), `removed` là Gaussian sẽ bị loại (đỏ). Mỗi mảng là các
   * xyz liên tiếp trong khung object-local, con của entity vật. Gọi lại thì thay bộ cũ; cả hai mảng rỗng thì gỡ hết.
   */
  setPointSets(objectId: string, added: Float32Array, removed: Float32Array): void {
    this.releasePoints(objectId);
    const parent = this.parentOf(objectId);
    if (!parent) return;
    const app = this.host.application();
    const root = new Entity(`r2s-points-${objectId}`, app);
    const record: PointRecord = { root, meshes: [], materials: [] };
    const sets: [string, Float32Array, string][] = [
      ["added", added, themeColor("--studio-sage", "#22c55e")],
      ["removed", removed, themeColor("--studio-rust", "#ef4444")],
    ];
    for (const [label, positions, hex] of sets) {
      if (positions.length < 3) continue;
      const mesh = new Mesh(app.graphicsDevice);
      mesh.setPositions(positions);
      mesh.update(PRIMITIVE_POINTS);
      const material = pointMaterial(hex);
      const child = new Entity(`r2s-points-${objectId}-${label}`, app);
      child.addComponent("render", { meshInstances: [new MeshInstance(mesh, material)], castShadows: false });
      root.addChild(child);
      record.meshes.push(mesh);
      record.materials.push(material);
    }
    if (record.meshes.length === 0) {
      root.destroy();
      return;
    }
    parent.addChild(root);
    this.points.set(objectId, record);
  }

  /**
   * Đổi trạng thái hiển thị của vỏ đang có: `pending` làm mờ tới khi vỏ mới về, `warning` đổi màu cam và giữ độ mờ của
   * kiểu vỏ. Vỏ `normal` trở lại thì có màu và độ mờ gốc. Vật chưa có vỏ thì không làm gì.
   */
  setTone(objectId: string, tone: ShellTone): void {
    const record = this.shells.get(objectId);
    if (!record || record.tone === tone) return;
    record.tone = tone;
    this.applyTone(record);
  }

  /** Gỡ vỏ và điểm của một vật, hoặc của mọi vật khi không truyền `objectId`. */
  clear(objectId?: string): void {
    const ids = objectId === undefined ? new Set([...this.shells.keys(), ...this.points.keys()]) : [objectId];
    for (const id of ids) {
      this.releaseShell(id);
      this.releasePoints(id);
    }
  }

  /** Gỡ toàn bộ vỏ. Sau khi gọi, các lời gọi khác không làm gì; gọi lại cũng an toàn. */
  destroy(): void {
    if (this.destroyed) return;
    this.clear();
    if (this.subscribed) this.host.application().off("update", this.onUpdate);
    this.subscribed = false;
    this.destroyed = true;
  }

  /** Đăng ký nhịp khung hình khi có vỏ đầu tiên; không đăng ký trước để không chạm viewer khi chưa có gì để vẽ. */
  private subscribe(): void {
    if (this.subscribed) return;
    this.subscribed = true;
    this.host.application().on("update", this.onUpdate);
  }

  /** Màu và độ mờ theo trạng thái: thường (độ mờ theo kiểu), đang tính (mờ 0,12), hoặc xem trước lỗi (màu cam). */
  private applyTone(record: ShellRecord): void {
    const color = record.tone === "warning" ? themeColor("--studio-ochre", "#f59e0b") : themeColor("--studio-sage", "#2dd4bf");
    record.fill.emissive = new Color().fromString(color);
    record.fill.opacity = record.tone === "pending" ? PENDING_OPACITY : SHELL_OPACITY[record.style];
    record.fill.emissiveIntensity = 1;
    record.fill.update();
    if (record.wire) {
      record.wire.emissive = new Color().fromString(color);
      record.wire.opacity = record.tone === "pending" ? PENDING_OPACITY : WIRE_OPACITY;
      record.wire.update();
    }
    record.pulsing = false;
  }

  private parentOf(objectId: string): Entity | null {
    if (this.destroyed || !this.host.isAlive()) return null;
    return this.host.objectEntity(objectId);
  }

  /** Gỡ entity, vật liệu và asset của vỏ; asset được bỏ khỏi registry rồi unload. */
  private releaseShell(objectId: string): void {
    const record = this.shells.get(objectId);
    if (!record) return;
    this.shells.delete(objectId);
    this.revoke(record);
    record.settle();
    record.root.destroy();
    record.fill.destroy();
    record.wire?.destroy();
    this.host.application().assets?.remove(record.asset);
    record.asset.unload();
  }

  /** Gỡ điểm của một vật: entity, mesh và vật liệu của chúng. */
  private releasePoints(objectId: string): void {
    const record = this.points.get(objectId);
    if (!record) return;
    this.points.delete(objectId);
    record.root.destroy();
    for (const mesh of record.meshes) mesh.destroy();
    for (const material of record.materials) material.destroy();
  }

  private revoke(record: ShellRecord): void {
    if (!record.blobUrl) return;
    URL.revokeObjectURL(record.blobUrl);
    record.blobUrl = null;
  }
}
