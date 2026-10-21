/**
 * Suy ra lớp hiển thị từ SceneIR.
 *
 * Toàn bộ file này là hàm thuần, không import Three.js và không đụng WebGL, nên
 * test được trong jsdom. Đó là chủ ý: phần dễ sai nhất của viewer là ánh xạ
 * SceneIR → layer và bind checksum, không phải phần vẽ.
 *
 * Bốn bất biến:
 * - Transform canonical lấy từ SceneIR, không lấy từ state của Three.js.
 * - Mỗi layer giữ `checksum` của artifact sinh ra nó, để UI hiện được cái đang vẽ.
 * - Object `active: false` vẫn tạo layer nhưng mặc định ẩn — ẩn/hiện là lựa chọn
 *   xem, không phải sửa canonical state.
 */

import type { ArtifactRef, ColliderSpec, SceneIR, SceneObject, Transform } from "@/lib/contracts/api";

export const VIEW_MODES = ["VISUAL", "GEOMETRY", "POINT_CLOUD", "COLLIDER"] as const;
export type ViewMode = (typeof VIEW_MODES)[number];

export const VIEW_MODE_LABELS: Record<ViewMode, string> = {
  VISUAL: "3DGS Visual",
  GEOMETRY: "Geometry mesh",
  POINT_CLOUD: "Point cloud",
  COLLIDER: "Collider",
};

/** Ba view kỹ thuật dựng bằng Three.js; VISUAL cần renderer Gaussian. */
export const THREE_JS_VIEW_MODES: readonly ViewMode[] = ["GEOMETRY", "POINT_CLOUD", "COLLIDER"];

/**
 * Canonical của dự án là **Z-up** (`coordinates.py` CANONICAL_UP_AXIS = "Z"), còn
 * Three.js là **Y-up**. Bản cũ copy thẳng `translation_xyz` vào `position` và đặt
 * camera theo Y-up, nên **mọi object bị vẽ sai trục** — scene sẽ xoay 90°.
 *
 * Dùng đúng phép quy đổi của repo (`rgb/voxel.py` `native_from_world`):
 * R_x(-90°), tức (x, y, z) → (x, z, −y). Giữ handedness và đơn vị mét.
 */
export function toRendererPoint(point: [number, number, number]): [number, number, number] {
  const [x, y, z] = point;
  return [x, z, -y];
}

/** Cùng phép quy đổi cho quaternion, quy ước xyzw như canonical. */
export function toRendererQuaternion(
  quaternion: [number, number, number, number],
): [number, number, number, number] {
  const [x, y, z, w] = quaternion;
  return [x, z, -y, w];
}

export interface LayerTransform {
  parent_frame: string;
  local_frame: string;
  translation_xyz: [number, number, number];
  rotation_quaternion_xyzw: [number, number, number, number];
}

export interface GeometryLayer {
  kind: "geometry" | "point_cloud";
  /** `scene` cho environment, `object` cho SceneObject. */
  owner: "scene" | "object";
  object_id: string | null;
  label: string;
  reference: ArtifactRef;
  checksum: string;
  transform: LayerTransform;
  /** Canonical `active` của object; không phải lựa chọn ẩn/hiện của người xem. */
  canonical_active: boolean;
  /**
   * SceneIR chưa có ref point cloud riêng. View điểm chỉ đọc vertex của geometry
   * PLY; ref không có loader tương ứng phải báo provisional, không vẽ dữ liệu giả.
   */
  provisional: boolean;
}

export interface ColliderLayer {
  kind: "collider";
  owner: "scene" | "object";
  object_id: string | null;
  label: string;
  collider_id: string;
  collider_type: ColliderSpec["collider_type"];
  reference: ArtifactRef | null;
  checksum: string | null;
  transform: LayerTransform;
  dimensions_xyz_m: [number, number, number];
  has_dimensions: boolean;
  canonical_active: boolean;
}

export type ViewerLayer = GeometryLayer | ColliderLayer;

export interface SceneLayers {
  scene_id: string;
  scene_revision: string;
  scene_checksum: string;
  geometry: GeometryLayer[];
  colliders: ColliderLayer[];
  /** Tất cả layer theo thứ tự: geometry trước, colliders sau. */
  all: ViewerLayer[];
}

/** AABB mặc định cho collider thiếu `dimensions_xyz_m` — hiện rõ là thiếu dữ liệu. */
export const MISSING_DIMENSIONS: [number, number, number] = [0.1, 0.1, 0.1];

function toLayerTransform(transform: Transform): LayerTransform {
  return {
    parent_frame: transform.parent_frame,
    local_frame: transform.local_frame,
    translation_xyz: [...transform.translation_xyz],
    rotation_quaternion_xyzw: [...transform.rotation_quaternion_xyzw],
  };
}

/**
 * Gộp transform của collider (object → collider) với transform của object
 * (world → object) để ra vị trí trong world.
 *
 * Contract chỉ cho collider parent vào `SceneObject.local_frame`, nên chuỗi ở
 * đây luôn đúng hai mắt xích. Sai lệch được báo bằng lỗi chứ không đoán.
 */
export function composeColliderTransform(object: SceneObject, collider: ColliderSpec): LayerTransform {
  if (collider.local_transform.parent_frame !== object.local_frame) {
    throw new Error(
      `lưới va chạm ${collider.collider_id} không gắn đúng vào vật ${object.local_frame}`,
    );
  }
  return {
    parent_frame: object.transform.parent_frame,
    // Frame của collider nằm trong `local_transform`, không phải trên ColliderSpec.
    local_frame: collider.local_transform.local_frame,
    translation_xyz: composeTranslation(object.transform, collider.local_transform),
    rotation_quaternion_xyzw: multiplyQuaternions(
      object.transform.rotation_quaternion_xyzw,
      collider.local_transform.rotation_quaternion_xyzw,
    ),
  };
}

/** Dịch chuyển của collider trong frame cha: t_world = t_obj + R_obj · t_local. */
export function composeTranslation(parent: Transform, local: Transform): [number, number, number] {
  const rotated = rotateVector(parent.rotation_quaternion_xyzw, local.translation_xyz);
  return [parent.translation_xyz[0] + rotated[0], parent.translation_xyz[1] + rotated[1], parent.translation_xyz[2] + rotated[2]];
}

/** Nhân hai quaternion thứ tự xyzw. */
export function multiplyQuaternions(
  a: readonly [number, number, number, number],
  b: readonly [number, number, number, number],
): [number, number, number, number] {
  const [ax, ay, az, aw] = a;
  const [bx, by, bz, bw] = b;
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ];
}

/** Xoay vector bằng quaternion xyzw. */
export function rotateVector(
  quaternion: readonly [number, number, number, number],
  vector: readonly [number, number, number],
): [number, number, number] {
  const [x, y, z, w] = quaternion;
  const [vx, vy, vz] = vector;
  const t: [number, number, number] = [
    2 * (y * vz - z * vy),
    2 * (z * vx - x * vz),
    2 * (x * vy - y * vx),
  ];
  return [
    vx + w * t[0] + (y * t[2] - z * t[1]),
    vy + w * t[1] + (z * t[0] - x * t[2]),
    vz + w * t[2] + (x * t[1] - y * t[0]),
  ];
}

/** SceneIR → layer. Trả cả geometry lẫn collider; lọc theo view là việc của UI. */
export function buildSceneLayers(scene: SceneIR, sceneChecksum: string): SceneLayers {
  const geometry: GeometryLayer[] = [
    {
      kind: "geometry",
      owner: "scene",
      object_id: null,
      label: "Environment geometry",
      reference: scene.environment.geometry_ref,
      checksum: scene.environment.geometry_ref.artifact_checksum,
      transform: {
        parent_frame: scene.coordinate_system.world_frame,
        local_frame: scene.coordinate_system.world_frame,
        translation_xyz: [0, 0, 0],
        rotation_quaternion_xyzw: [0, 0, 0, 1],
      },
      canonical_active: true,
      provisional: !/\.(ply|glb)$/i.test(scene.environment.geometry_ref.artifact_uri),
    },
    {
      kind: "point_cloud",
      owner: "scene",
      object_id: null,
      label: "Environment point cloud",
      reference: scene.environment.geometry_ref,
      checksum: scene.environment.geometry_ref.artifact_checksum,
      transform: {
        parent_frame: scene.coordinate_system.world_frame,
        local_frame: scene.coordinate_system.world_frame,
        translation_xyz: [0, 0, 0],
        rotation_quaternion_xyzw: [0, 0, 0, 1],
      },
      canonical_active: true,
      provisional: !/\.ply$/i.test(scene.environment.geometry_ref.artifact_uri),
    },
  ];
  const colliders: ColliderLayer[] = [];

  for (const object of scene.objects) {
    geometry.push({
      kind: "geometry",
      owner: "object",
      object_id: object.id,
      label: `${object.name} — mesh`,
      reference: object.geometry_ref,
      checksum: object.geometry_ref.artifact_checksum,
      transform: toLayerTransform(object.transform),
      canonical_active: object.active,
      provisional: !/\.(ply|glb)$/i.test(object.geometry_ref.artifact_uri),
    });
    geometry.push({
      kind: "point_cloud",
      owner: "object",
      object_id: object.id,
      label: `${object.name} — point cloud`,
      reference: object.geometry_ref,
      checksum: object.geometry_ref.artifact_checksum,
      transform: toLayerTransform(object.transform),
      canonical_active: object.active,
      provisional: !/\.ply$/i.test(object.geometry_ref.artifact_uri),
    });
    if (object.collider) {
      colliders.push(buildColliderLayer(object, object.collider));
    }
  }

  const collisionSource = scene.environment.collision_source_ref;
  const environmentCollider = scene.environment.collider_ref;
  const lidarSelected = collisionSource?.artifact_type === "LidarCollisionCandidate";
  const sourceIsEffectiveCollider =
    collisionSource != null && environmentCollider != null && collisionSource.artifact_checksum === environmentCollider.artifact_checksum;
  if (collisionSource && !sourceIsEffectiveCollider) {
    colliders.unshift({
      kind: "collider",
      owner: "scene",
      object_id: null,
      label: lidarSelected ? "LiDAR collision source" : "Selected collision source",
      collider_id: "environment-source",
      collider_type: "AABB",
      reference: collisionSource,
      checksum: collisionSource.artifact_checksum,
      transform: {
        parent_frame: scene.coordinate_system.world_frame,
        local_frame: scene.coordinate_system.world_frame,
        translation_xyz: [0, 0, 0],
        rotation_quaternion_xyzw: [0, 0, 0, 1],
      },
      dimensions_xyz_m: MISSING_DIMENSIONS,
      has_dimensions: false,
      canonical_active: true,
    });
  }

  if (environmentCollider) {
    colliders.unshift({
      kind: "collider",
      owner: "scene",
      object_id: null,
      label: lidarSelected
        ? sourceIsEffectiveCollider
          ? "LiDAR collision candidate"
          : "LiDAR-derived environment collider"
        : collisionSource
          ? "Selected-source environment collider"
          : "Environment collider",
      collider_id: "environment",
      collider_type: "AABB",
      reference: environmentCollider,
      checksum: environmentCollider.artifact_checksum,
      transform: {
        parent_frame: scene.coordinate_system.world_frame,
        local_frame: scene.coordinate_system.world_frame,
        translation_xyz: [0, 0, 0],
        rotation_quaternion_xyzw: [0, 0, 0, 1],
      },
      dimensions_xyz_m: MISSING_DIMENSIONS,
      has_dimensions: false,
      canonical_active: true,
    });
  }

  return {
    scene_id: scene.scene_id,
    scene_revision: scene.scene_revision,
    scene_checksum: sceneChecksum,
    geometry,
    colliders,
    all: [...geometry, ...colliders],
  };
}

function buildColliderLayer(object: SceneObject, collider: ColliderSpec): ColliderLayer {
  return {
    kind: "collider",
    owner: "object",
    object_id: object.id,
    label: `${object.name} — ${collider.collider_type}`,
    collider_id: collider.collider_id,
    collider_type: collider.collider_type,
    reference: collider.geometry_ref,
    checksum: collider.geometry_ref?.artifact_checksum ?? null,
    transform: composeColliderTransform(object, collider),
    dimensions_xyz_m: collider.dimensions_xyz_m ?? MISSING_DIMENSIONS,
    has_dimensions: collider.dimensions_xyz_m != null,
    canonical_active: object.active,
  };
}

/** Layer nào được vẽ ở view hiện tại. */
export function visibleLayers(layers: SceneLayers, mode: ViewMode): ViewerLayer[] {
  const hidden = (layer: ViewerLayer) => !layer.canonical_active;
  switch (mode) {
    case "GEOMETRY":
      return layers.geometry.filter((layer) => layer.kind === "geometry" && !hidden(layer));
    case "POINT_CLOUD":
      return layers.geometry.filter((layer) => layer.kind === "point_cloud" && !hidden(layer));
    case "COLLIDER":
      return layers.colliders.filter((layer) => !hidden(layer));
    case "VISUAL":
      // Visual không nằm trong SceneIR geometry; nó do VisualArtifact cấp.
      return [];
  }
}

/** Id ổn định cho layer, dùng làm React key và state ẩn/hiện. */
export function layerKey(layer: ViewerLayer): string {
  const owner = layer.object_id ?? "scene";
  return layer.kind === "collider" ? `${owner}:collider:${layer.collider_id}` : `${owner}:${layer.kind}`;
}
