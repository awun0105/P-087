/**
 * Hệ trục của nội dung 3DGS và cách đặt nó vào không gian hiển thị Y-up của PlayCanvas.
 *
 * `supersplat-viewer` luôn xoay splat 180° quanh Z: đúng cho output Brush/COLMAP (Y hướng
 * xuống, Z hướng tới trước) nhưng sai cho artifact hệ mét canonical của REC-06 (Z-up, sàn
 * z = 0) — scene nằm nghiêng 90°, sàn thành tường. Mỗi artifact nói rõ hệ nguồn của nó; viewer
 * chỉ đổi phép xoay hiển thị, không sửa dữ liệu canonical.
 *
 * Camera khởi đầu lấy từ camera quay đầu tiên (parent_from_camera, quy ước OpenCV: x phải,
 * y xuống, z tới trước), đổi sang cùng không gian hiển thị, để mọi lớp mở ra cùng một góc nhìn.
 */

/** `colmap`: world SfM của COLMAP/Brush (Y xuống). `z_up`: canonical REC-06, mét, sàn z = 0. `identity`: toạ độ gốc không xoay. */
export type SourceFrame = "colmap" | "z_up" | "identity";

export type Vec3 = [number, number, number];

/** Euler XYZ (độ) của entity nội dung trong không gian hiển thị Y-up. */
export const DISPLAY_EULER: Record<SourceFrame, Vec3> = {
  colmap: [0, 0, 180], // giữ đúng mặc định upstream: (x, y, z) → (−x, −y, z)
  z_up: [-90, 0, 0], // (x, y, z) → (x, z, −y): Z-up thành Y-up, không soi gương
  identity: [0, 0, 0], // gốc: không xoay
};

/** Điểm hệ nguồn → không gian hiển thị (cùng phép xoay với `DISPLAY_EULER`). */
export function toDisplay(frame: SourceFrame, [x, y, z]: Vec3): Vec3 {
  if (frame === "colmap") return [-x, -y, z];
  if (frame === "z_up") return [x, z, -y];
  return [x, y, z];
}

/** Xoay vector bằng quaternion xyzw. */
export function rotate([qx, qy, qz, qw]: readonly [number, number, number, number], [x, y, z]: Vec3): Vec3 {
  // v' = v + 2w(q×v) + 2 q×(q×v)
  const cx = qy * z - qz * y;
  const cy = qz * x - qx * z;
  const cz = qx * y - qy * x;
  return [
    x + 2 * (qw * cx + qy * cz - qz * cy),
    y + 2 * (qw * cy + qz * cx - qx * cz),
    z + 2 * (qw * cz + qx * cy - qy * cx),
  ];
}

export interface CameraMarkerLike {
  center: Vec3;
  rotation_xyzw: [number, number, number, number];
}

/** Pose camera theo format settings của supersplat-viewer (không gian hiển thị). */
export interface DisplayCameraPose {
  position: Vec3;
  target: Vec3;
  fov: number;
}

/**
 * Đặt camera viewer tại camera quay đầu tiên, nhìn theo hướng của nó. Tâm xoay (target) ở phía
 * trước 35% đường chéo quỹ đạo (2–15 đơn vị): orbit của PlayCanvas zoom theo tỉ lệ khoảng cách
 * tới tâm (`dist × (1 + delta)`), tâm quá gần làm mỗi nấc cuộn chỉ đi vài chục cm.
 */
export function recordingCameraPose(
  frame: SourceFrame,
  cameras: readonly CameraMarkerLike[],
  fov = 60,
): DisplayCameraPose | undefined {
  const first = cameras[0];
  if (!first) return undefined;
  const low = [0, 1, 2].map((axis) => Math.min(...cameras.map((camera) => camera.center[axis])));
  const high = [0, 1, 2].map((axis) => Math.max(...cameras.map((camera) => camera.center[axis])));
  const diagonal = Math.hypot(high[0] - low[0], high[1] - low[1], high[2] - low[2]);
  const distance = Math.min(Math.max(diagonal * 0.35, 2), 15);
  const forward = rotate(first.rotation_xyzw, [0, 0, 1]);
  const target: Vec3 = [
    first.center[0] + forward[0] * distance,
    first.center[1] + forward[1] * distance,
    first.center[2] + forward[2] * distance,
  ];
  return { position: toDisplay(frame, first.center), target: toDisplay(frame, target), fov };
}

/**
 * Góc nhìn tới một vật (hệ canonical Z-up), trả pose ở không gian hiển thị cho annotation.
 *
 * Ưu tiên đứng tại camera quay thật gần nhất đã thấy vật (vật nằm phía trước, lệch trục ≤ ~45°,
 * cách 1,5–8 m): camera đó chắc chắn có đường nhìn thông, không bị vật khác chắn. Không có camera
 * nào như vậy thì lùi theo phương ngang về phía camera đầu tiên, nâng cao hơn tâm vật.
 */
export function objectViewPose(
  center: Vec3,
  dimensions: Vec3,
  cameras: readonly CameraMarkerLike[],
  fov = 60,
): DisplayCameraPose {
  let best: CameraMarkerLike | undefined;
  let bestDistance = Infinity;
  for (const camera of cameras) {
    const offset: Vec3 = [center[0] - camera.center[0], center[1] - camera.center[1], center[2] - camera.center[2]];
    const distance = Math.hypot(...offset);
    if (distance < 1.5 || distance > 8 || distance >= bestDistance) continue;
    const forward = rotate(camera.rotation_xyzw, [0, 0, 1]);
    const alignment = (forward[0] * offset[0] + forward[1] * offset[1] + forward[2] * offset[2]) / distance;
    if (alignment < 0.7) continue;
    best = camera;
    bestDistance = distance;
  }
  if (best) return { position: toDisplay("z_up", best.center), target: toDisplay("z_up", center), fov };
  const size = Math.max(...dimensions);
  const distance = Math.max(2, size * 2.5);
  const from = cameras[0]?.center;
  let dx = (from?.[0] ?? center[0] - 1) - center[0];
  let dy = (from?.[1] ?? center[1]) - center[1];
  const length = Math.hypot(dx, dy);
  if (length < 1e-6) {
    dx = -1;
    dy = 0;
  } else {
    dx /= length;
    dy /= length;
  }
  const eye: Vec3 = [center[0] + dx * distance, center[1] + dy * distance, center[2] + Math.max(0.8, size)];
  return { position: toDisplay("z_up", eye), target: toDisplay("z_up", center), fov };
}

export interface BoundingBoxLike {
  min: Vec3;
  max: Vec3;
}

/**
 * Fallback góc nhìn bên trong không gian khi scene không có quỹ đạo camera COLMAP
 * (ví dụ người dùng import file PLY/SOG từ ngoài vào). Đặt camera ở tầm mắt (1.5m),
 * nhìn dọc trục dài của không gian thay vì lùi ra ngoài hư không.
 */
export function interiorFallbackPose(
  frame: SourceFrame,
  box: BoundingBoxLike,
  fov = 60,
): DisplayCameraPose {
  const dx = box.max[0] - box.min[0];
  const dy = box.max[1] - box.min[1];
  const dz = box.max[2] - box.min[2];
  const midX = (box.min[0] + box.max[0]) / 2;
  const midY = (box.min[1] + box.max[1]) / 2;
  const midZ = (box.min[2] + box.max[2]) / 2;

  let eye: Vec3;
  let target: Vec3;

  if (frame === "z_up") {
    const eyeZ = Math.min(box.min[2] + 1.5, midZ);
    if (dx >= dy) {
      eye = [box.min[0] + dx * 0.2, midY, eyeZ];
      target = [box.max[0], midY, eyeZ];
    } else {
      eye = [midX, box.min[1] + dy * 0.2, eyeZ];
      target = [midX, box.max[1], eyeZ];
    }
  } else {
    // colmap: Y hướng xuống, Z hướng tới trước; X sang phải.
    const eyeY = box.min[1] + dy * 0.5;
    eye = [midX, eyeY, box.min[2] + dz * 0.2];
    target = [midX, eyeY, box.max[2]];
  }

  return { position: toDisplay(frame, eye), target: toDisplay(frame, target), fov };
}

/** Cấu trúc animation track camera theo format ExperienceSettings của supersplat-viewer. */
export interface TrajectoryAnimTrack {
  name: string;
  duration: number;
  frameRate: number;
  loopMode: "none" | "repeat" | "pingpong";
  interpolation: "step" | "spline";
  smoothness: number;
  keyframes: {
    times: number[];
    values: {
      position: number[];
      target: number[];
      fov: number[];
    };
  };
}

/**
 * Xây dựng spline animation track cho camera viewer theo đúng chuỗi camera quay gốc.
 * Vị trí camera và điểm nhìn (target) được chuyển đổi đồng bộ sang hệ hiển thị Y-up.
 */
export function buildTrajectoryAnimTrack(
  frame: SourceFrame,
  cameras: readonly CameraMarkerLike[],
  options?: {
    frameRate?: number;
    maxKeyframes?: number;
    fov?: number;
  },
): TrajectoryAnimTrack | undefined {
  if (!cameras || cameras.length < 2) return undefined;

  const frameRate = Math.max(1, Math.min(120, Math.round(options?.frameRate ?? 30)));
  const maxKeyframes = Math.min(options?.maxKeyframes ?? 600, 1000);
  const fov = options?.fov ?? 60;

  // Tính khoảng cách nhìn tới trước (lookDistance) từ bounding box của quỹ đạo
  const low = [0, 1, 2].map((axis) => Math.min(...cameras.map((c) => c.center[axis])));
  const high = [0, 1, 2].map((axis) => Math.max(...cameras.map((c) => c.center[axis])));
  const diagonal = Math.hypot(high[0] - low[0], high[1] - low[1], high[2] - low[2]);
  const lookDistance = Math.min(Math.max(diagonal * 0.35, 2), 15);

  const total = cameras.length;
  const stride = total > maxKeyframes ? Math.ceil(total / maxKeyframes) : 1;
  const indices: number[] = [];
  for (let i = 0; i < total; i += stride) {
    indices.push(i);
  }
  if (indices[indices.length - 1] !== total - 1) {
    indices.push(total - 1);
  }

  const times: number[] = [];
  const positions: number[] = [];
  const targets: number[] = [];
  const fovs: number[] = [];

  for (const idx of indices) {
    const cam = cameras[idx];
    const forward = rotate(cam.rotation_xyzw, [0, 0, 1]);
    const targetPoint: Vec3 = [
      cam.center[0] + forward[0] * lookDistance,
      cam.center[1] + forward[1] * lookDistance,
      cam.center[2] + forward[2] * lookDistance,
    ];

    const displayPos = toDisplay(frame, cam.center);
    const displayTarget = toDisplay(frame, targetPoint);

    times.push(idx);
    positions.push(...displayPos);
    targets.push(...displayTarget);
    fovs.push(fov);
  }

  const lastTime = times[times.length - 1] ?? 0;
  const duration = Math.max(0.1, lastTime / frameRate);

  return {
    name: "Video Trajectory",
    duration,
    frameRate,
    loopMode: "none",
    interpolation: "spline",
    smoothness: 0,
    keyframes: {
      times,
      values: {
        position: positions,
        target: targets,
        fov: fovs,
      },
    },
  };
}
