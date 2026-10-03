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

import { parseGlbMesh, type TriangleMesh } from "@/features/viewer/glb-mesh";
import type { OverlayObject, SceneOverlay } from "@/features/viewer/scene-overlay";
import { ScenePhysics, displayToCanonical, loadAmmo, type PhysicsObjectSpec } from "@/features/viewer/scene-physics";
import type { Vec3 } from "@/features/viewer/source-frame";
import { WALK_EYE_HEIGHT_M } from "@/features/viewer/third-person";

/** Một vật động như SceneIR mô tả, kèm URL collider để dựng bao lồi. */
export interface PhysicsObjectInput {
  id: string;
  position: Vec3;
  rotation_xyzw: [number, number, number, number];
  colliderUrl: string | null;
  dimensions: Vec3 | null;
  mass_kg: number;
  friction: number;
  restitution: number;
}

export type PhysicsStatus =
  | { state: "off" }
  | { state: "loading" }
  | { state: "ready"; objects: number }
  | { state: "failed"; message: string };

async function fetchMesh(url: string, signal: AbortSignal): Promise<TriangleMesh> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return parseGlbMesh(await response.arrayBuffer());
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

export function usePhysicsPlay({
  app,
  overlay,
  walking,
  collisionUrl,
  objects,
  overlayObjects,
}: {
  app: AppBase | null;
  overlay: SceneOverlay | null;
  walking: boolean;
  /** Lưới va chạm đã khoét vùng gốc của vật động, ở không gian hiển thị (cùng URL viewer dùng cho người đi). */
  collisionUrl: string | null;
  objects: readonly PhysicsObjectInput[];
  /** Pose của vật theo SceneIR, để trả lớp phủ về đúng chỗ khi dừng/đặt lại. */
  overlayObjects: readonly OverlayObject[];
}): { status: PhysicsStatus; reset: () => void } {
  const [status, setStatus] = useState<PhysicsStatus>({ state: "off" });
  const physicsRef = useRef<ScenePhysics | null>(null);
  const restore = useRef(overlayObjects);
  useEffect(() => {
    restore.current = overlayObjects;
  }, [overlayObjects]);
  const enabled = walking && objects.length > 0 && app !== null && overlay !== null && collisionUrl !== null;
  // Dựng lại khi tập vật động hoặc lưới đổi, không khi chỉ đổi màu/chọn vật.
  const key = JSON.stringify(objects);

  useEffect(() => {
    if (!enabled || !app || !overlay || !collisionUrl) return;
    const controller = new AbortController();
    let physics: ScenePhysics | null = null;
    const specs: PhysicsObjectInput[] = JSON.parse(key);
    const tick = (dt: number) => {
      if (!physics) return;
      const camera = app.root?.findComponent("camera") as { entity: Entity } | null;
      const eye = camera?.entity.getPosition();
      const feet = eye ? displayToCanonical([eye.x, eye.y, eye.z]) : null;
      if (feet) feet[2] -= WALK_EYE_HEIGHT_M;
      for (const [id, pose] of physics.step(dt, feet)) overlay.setObjectPose(id, pose.position, pose.rotation_xyzw);
      app.renderNextFrame = true;
    };
    queueMicrotask(() => { if (!controller.signal.aborted) setStatus({ state: "loading" }); });
    void (async () => {
      try {
        const [ammo, environment, hulls] = await Promise.all([
          loadAmmo(),
          fetchMesh(collisionUrl, controller.signal).then(toCanonical),
          Promise.all(
            specs.map((item) =>
              item.colliderUrl
                ? fetchMesh(item.colliderUrl, controller.signal).then((mesh) => mesh.positions, () => null)
                : Promise.resolve(null),
            ),
          ),
        ]);
        if (controller.signal.aborted) return;
        const bodies: PhysicsObjectSpec[] = specs.map((item, index) => ({
          id: item.id,
          position: item.position,
          rotation_xyzw: item.rotation_xyzw,
          hull: hulls[index],
          dimensions: item.dimensions,
          mass_kg: item.mass_kg,
          friction: item.friction,
          restitution: item.restitution,
        }));
        physics = new ScenePhysics(ammo, environment, bodies);
        physicsRef.current = physics;
        app.on("update", tick);
        setStatus({ state: "ready", objects: bodies.length });
      } catch (error: unknown) {
        if (!controller.signal.aborted) setStatus({ state: "failed", message: error instanceof Error ? error.message : String(error) });
      }
    })();
    return () => {
      controller.abort();
      app.off("update", tick);
      physics?.destroy();
      physicsRef.current = null;
      // Rời chế độ chơi: mọi vật về đúng chỗ của SceneIR.
      overlay.setObjects(restore.current);
      setStatus({ state: "off" });
    };
  }, [enabled, app, overlay, collisionUrl, key]);

  const reset = useCallback(() => {
    physicsRef.current?.reset();
    overlay?.setObjects(restore.current);
  }, [overlay]);

  return { status, reset };
}
