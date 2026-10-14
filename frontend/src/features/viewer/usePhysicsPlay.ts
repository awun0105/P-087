"use client";

/**
 * Chạy vật lý phía trình duyệt khi người dùng Đi bộ trong scene có vật động (H5, ADR 0010).
 *
 * Bật chế độ Đi bộ → tải ammo.js, lưới va chạm đã khoét (cùng file viewer dùng cho người đi) và collider của từng vật
 * động, dựng thế giới vật lý; mỗi frame đặt thân người đi theo vị trí camera của viewer rồi chép pose của vật sang lớp
 * phủ. Rời chế độ Đi bộ hoặc bấm Đặt lại → vật về đúng pose của SceneIR. Không ghi gì về backend.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { AppBase, Entity } from "playcanvas";

import { parseGlbCollider, parseGlbMesh, type ColliderMeshPart, type TriangleMesh } from "@/features/viewer/glb-mesh";
import type { OverlayObject, SceneOverlay } from "@/features/viewer/scene-overlay";
import { ScenePhysics, displayToCanonical, loadAmmo, validateConvexPart, validateTriangleMesh, type AmmoModule, type PhysicsObjectSpec } from "@/features/viewer/scene-physics";
import type { Vec3 } from "@/features/viewer/source-frame";
import { ObjectCameraCollision } from "@/features/viewer/camera-collision";
import type { CollisionQuery } from "@playcanvas/supersplat-viewer/viewer";
import { WALK_EYE_HEIGHT_M } from "@/features/viewer/third-person";

/** Một vật động như SceneIR mô tả, kèm URL collider để dựng bao lồi. */
export interface PhysicsObjectInput {
  id: string;
  dynamic?: boolean;
  colliderType?: string;
  position: Vec3;
  rotation_xyzw: [number, number, number, number];
  /** GLB đã bake trong collider-local frame canonical; không phải display-space GLB. */
  colliderUrl: string | null;
  /** Child collider frame relative to the SceneObject; applied to hull vertices before simulation. */
  colliderLocalTransform: {
    translation_xyz: Vec3;
    rotation_quaternion_xyzw: [number, number, number, number];
  } | null;
  dimensions: Vec3 | null;
  mass_kg: number | null;
  friction: number;
  restitution: number;
}

export type PhysicsStatus =
  | { state: "off" }
  | { state: "loading" }
  | { state: "ready"; objects: number }
  | { state: "failed"; message: string };

export function browserPhysicsBlocker(objects: readonly PhysicsObjectInput[]): string | null {
  for (const item of objects) {
    const type = item.colliderType ?? (item.colliderUrl ? "CONVEX_HULL" : "AABB");
    if (!["AABB", "OBB", "CONVEX_HULL", "CONVEX_DECOMPOSITION", "SIMPLIFIED_MESH"].includes(type)) return `${item.id}: unsupported collider type ${type}`;
    if (item.dynamic !== false && (item.mass_kg === null || !Number.isFinite(item.mass_kg) || item.mass_kg <= 0)) return `${item.id}: dynamic body requires positive authored mass`;
    if (item.dynamic !== false && type === "SIMPLIFIED_MESH") return `${item.id}: dynamic concave triangle mesh is unsupported`;
    if (["AABB", "OBB"].includes(type)) {
      if (!item.dimensions || item.dimensions.some(value => !Number.isFinite(value) || value <= 0)) return `${item.id}: thiếu kích thước box collider`;
    } else if (!item.colliderUrl) return `${item.id}: thiếu collider artifact`;
  }
  return null;
}

async function fetchMesh(url: string, signal: AbortSignal, frame: "display_world" | "canonical_collider_local"): Promise<TriangleMesh> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const mesh = parseGlbMesh(await response.arrayBuffer());
  return frame === "display_world" ? toCanonical(mesh) : mesh;
}

/** Lưới va chạm của viewer ở không gian hiển thị → hệ canonical của thế giới vật lý. */
function toCanonical(mesh: TriangleMesh): TriangleMesh {
  const positions = new Float32Array(mesh.positions.length);
  for (let i = 0; i < positions.length; i += 3) {
    const [x, y, z] = displayToCanonical([mesh.positions[i], mesh.positions[i + 1], mesh.positions[i + 2]]);
    positions[i] = x;
    positions[i + 1] = y;
    positions[i + 2] = z;
  }
  return { positions, indices: mesh.indices };
}

export function transformColliderHullToObjectFrame(
  points: Float32Array,
  transform: PhysicsObjectInput["colliderLocalTransform"],
): Float32Array {
  if (!transform) return points;
  const result = new Float32Array(points.length);
  const [offsetX, offsetY, offsetZ] = transform.translation_xyz;
  const [qx, qy, qz, qw] = transform.rotation_quaternion_xyzw;
  for (let index = 0; index < points.length; index += 3) {
    const x = points[index];
    const y = points[index + 1];
    const z = points[index + 2];
    const uvx = qy * z - qz * y;
    const uvy = qz * x - qx * z;
    const uvz = qx * y - qy * x;
    const uuvx = qy * uvz - qz * uvy;
    const uuvy = qz * uvx - qx * uvz;
    const uuvz = qx * uvy - qy * uvx;
    result[index] = x + 2 * (qw * uvx + uuvx) + offsetX;
    result[index + 1] = y + 2 * (qw * uvy + uuvy) + offsetY;
    result[index + 2] = z + 2 * (qw * uvz + uuvz) + offsetZ;
  }
  return result;
}

export function fallbackColliderHull(
  dimensions: Vec3 | null,
  transform: PhysicsObjectInput["colliderLocalTransform"],
): Float32Array | null {
  if (!dimensions || !transform) return null;
  const [qx, qy, qz, qw] = transform.rotation_quaternion_xyzw;
  const identity =
    transform.translation_xyz.every((value) => Math.abs(value) < 1e-8) &&
    Math.abs(qx) < 1e-8 &&
    Math.abs(qy) < 1e-8 &&
    Math.abs(qz) < 1e-8 &&
    Math.abs(Math.abs(qw) - 1) < 1e-8;
  if (identity) return null;
  const points: number[] = [];
  for (const x of [-dimensions[0] / 2, dimensions[0] / 2]) {
    for (const y of [-dimensions[1] / 2, dimensions[1] / 2]) {
      for (const z of [-dimensions[2] / 2, dimensions[2] / 2]) points.push(x, y, z);
    }
  }
  return transformColliderHullToObjectFrame(new Float32Array(points), transform);
}

interface PreparedScene {
  identity: string;
  ammo: AmmoModule;
  environment: TriangleMesh;
  objects: PhysicsObjectSpec[];
  camera: ObjectCameraCollision;
}

export function usePhysicsPlay({ app, overlay, walking, collisionUrl, objects, overlayObjects, onObjectCollision }: {
  app: AppBase | null;
  overlay: SceneOverlay | null;
  walking: boolean;
  collisionUrl: string | null;
  objects: readonly PhysicsObjectInput[];
  overlayObjects: readonly OverlayObject[];
  onObjectCollision?: (collision: CollisionQuery | null) => void;
}): { status: PhysicsStatus; reset: () => void } {
  const [prepared, setPrepared] = useState<PreparedScene | null>(null);
  const [failure, setFailure] = useState<{ identity: string; message: string } | null>(null);
  const physicsRef = useRef<ScenePhysics | null>(null);
  const restore = useRef(overlayObjects);
  const cache = useRef(new Map<string, ColliderMeshPart[]>());
  useEffect(() => { restore.current = overlayObjects; }, [overlayObjects]);
  const enabled = objects.length > 0 && app !== null && overlay !== null && collisionUrl !== null;
  const key = JSON.stringify(objects);
  const identity = JSON.stringify([collisionUrl, key]);
  const data = prepared?.identity === identity ? prepared : null;

  // Prepare camera collision before permitting Walk. This allocates no native Ammo world outside Walk.
  useEffect(() => {
    if (!enabled || !collisionUrl) return;
    const controller = new AbortController();
    const specs: PhysicsObjectInput[] = JSON.parse(key);
    const urls = new Set(specs.filter(item => item.colliderUrl).map(item => `${item.colliderType ?? "CONVEX_HULL"}:${item.colliderUrl}`));
    for (const url of cache.current.keys()) if (!urls.has(url)) cache.current.delete(url);
    void (async () => {
      try {
        const blocker = browserPhysicsBlocker(specs);
        if (blocker) throw new Error(blocker);
        const [ammo, environment, shapes] = await Promise.all([
          loadAmmo(), fetchMesh(collisionUrl, controller.signal, "display_world"),
          Promise.all(specs.map(async item => {
            const type = item.colliderType ?? (item.colliderUrl ? "CONVEX_HULL" : "AABB");
            if (type === "AABB" || type === "OBB") return undefined;
            const url = item.colliderUrl!;
            const cacheKey = `${type}:${url}`;
            let parts = cache.current.get(cacheKey);
            if (!parts) {
              const response = await fetch(url, { signal: controller.signal });
              if (!response.ok) throw new Error(`${item.id}: collider HTTP ${response.status}`);
              try {
                parts = parseGlbCollider(await response.arrayBuffer()).parts;
                if (type === "CONVEX_HULL" && parts.length !== 1) throw new Error("CONVEX_HULL requires exactly one part");
                for (const part of parts) {
                  if (type === "SIMPLIFIED_MESH") validateTriangleMesh(part);
                  else validateConvexPart(part);
                }
              } catch (error: unknown) { throw new Error(`${item.id}: ${error instanceof Error ? error.message : String(error)}`); }
              if (controller.signal.aborted) return undefined;
              cache.current.set(cacheKey, parts);
            }
            if (type === "CONVEX_HULL" && parts.length !== 1) throw new Error(`${item.id}: CONVEX_HULL requires exactly one part`);
            return parts;
          })),
        ]);
        if (controller.signal.aborted) return;
        const bodies: PhysicsObjectSpec[] = specs.map((item,index) => ({
          ...item, colliderType: item.colliderType ?? (item.colliderUrl ? "CONVEX_HULL" : "AABB"),
          hull: null, parts: shapes[index], mass_kg: item.dynamic === false ? 0 : item.mass_kg!,
        }));
        const camera = new ObjectCameraCollision(bodies);
        setFailure(null);
        setPrepared({ identity, ammo, environment, objects: bodies, camera });
      } catch (error: unknown) {
        if (!controller.signal.aborted) setFailure({ identity, message: error instanceof Error ? error.message : String(error) });
      }
    })();
    return () => controller.abort();
  }, [enabled, collisionUrl, key, identity]);

  useEffect(() => {
    if (!data) return;
    onObjectCollision?.(data.camera);
    return () => onObjectCollision?.(null);
  }, [data, onObjectCollision]);
  useEffect(() => () => { data?.camera.clear(); }, [data]);

  useEffect(() => {
    if (!walking || !data || !app || !overlay) return;
    let physics: ScenePhysics;
    try { physics = new ScenePhysics(data.ammo, data.environment, data.objects); }
    catch (error: unknown) {
      queueMicrotask(() => setFailure({ identity, message: error instanceof Error ? error.message : String(error) }));
      return;
    }
    physicsRef.current = physics;
    const tick = (dt: number) => {
      const camera = app.root?.findComponent("camera") as { entity: Entity } | null;
      const eye = camera?.entity.getPosition();
      const feet = eye ? displayToCanonical([eye.x, eye.y, eye.z]) : null;
      if (feet) feet[2] -= WALK_EYE_HEIGHT_M;
      for (const [id, pose] of physics.step(dt, feet)) {
        overlay.setObjectPose(id, pose.position, pose.rotation_xyzw);
        data.camera.setPose(id, pose);
      }
      app.renderNextFrame = true;
    };
    app.on("update", tick);
    return () => {
      app.off("update", tick);
      physics.destroy();
      physicsRef.current = null;
      overlay.setObjects(restore.current);
      for (const item of data.objects) data.camera.setPose(item.id,{position:item.position,rotation_xyzw:item.rotation_xyzw});
    };
  }, [walking, data, app, overlay, identity]);

  const reset = useCallback(() => {
    physicsRef.current?.reset();
    overlay?.setObjects(restore.current);
    for (const item of data?.objects ?? []) data!.camera.setPose(item.id,{position:item.position,rotation_xyzw:item.rotation_xyzw});
  }, [overlay, data]);
  const status: PhysicsStatus = !enabled ? { state: "off" } : failure?.identity === identity
    ? { state: "failed", message: failure.message } : data ? { state: "ready", objects: data.objects.length } : { state: "loading" };
  return { status, reset };
}
