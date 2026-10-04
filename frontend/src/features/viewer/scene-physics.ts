/**
 * Vật lý trong trình duyệt cho scene tương tác (H5, ADR 0010): người đi đẩy được vật động.
 *
 * Thế giới vật lý ở hệ canonical của scene (mét, Z hướng lên, sàn z = 0) để pose của vật đọc/ghi thẳng như SceneIR:
 * - sàn: mặt phẳng z = 0 (lưới va chạm không chứa sàn — Isaac tự tạo sàn);
 * - tĩnh: lưới va chạm của scene đã khoét vùng gốc của vật động, chỉ giữ phần quanh các vật động;
 * - động: mỗi vật có `physics.dynamic` — bao lồi của collider (hoặc hộp theo kích thước), khối lượng và ma sát theo
 *   SceneIR;
 * - người đi: thân con nhộng động học bám theo vị trí người đi của viewer; chạm vào vật thì đẩy vật.
 *
 * Tương tác chỉ ở trình duyệt: không ghi SceneIR, không tạo revision. `reset()` đưa mọi vật về pose của SceneIR.
 */

import type { Vec3 } from "@/features/viewer/source-frame";
import type { TriangleMesh } from "@/features/viewer/glb-mesh";

type Quat = [number, number, number, number];

/* eslint-disable @typescript-eslint/no-explicit-any -- ammo.js là binding WebAssembly không có kiểu; mọi lời gọi
   tới nó nằm gọn trong file này và chỉ dùng các lớp đã kiểm trong test vật lý. */
export type AmmoModule = any;
type AmmoObject = any;
/* eslint-enable @typescript-eslint/no-explicit-any */

export interface PhysicsObjectSpec {
  id: string;
  /** Pose ở hệ canonical (như `SceneObject.transform`). */
  position: Vec3;
  rotation_xyzw: Quat;
  /** Đỉnh của collider trong khung của vật (xyz liên tiếp); null thì dùng hộp `dimensions`. */
  hull: Float32Array | null;
  dimensions: Vec3 | null;
  mass_kg: number;
  friction: number;
  restitution: number;
}

export interface Pose {
  position: Vec3;
  rotation_xyzw: Quat;
}

/** Thân người đi: bán kính và chiều cao của con nhộng (mét); chân đặt tại sàn của vị trí người đi. */
export const CHARACTER_RADIUS_M = 0.3;
export const CHARACTER_HEIGHT_M = 1.6;
/** Chỉ giữ lưới tĩnh trong khoảng này quanh các vật động: xa hơn thì vật không thể chạm tới trong lúc chơi. */
export const ENVIRONMENT_RADIUS_M = 6;
/** Số đỉnh tối đa cho một bao lồi: đủ giữ hình, không làm chậm bước mô phỏng. */
export const MAX_HULL_POINTS = 256;

const CF_KINEMATIC_OBJECT = 2;
const DISABLE_DEACTIVATION = 4;

/** Không gian hiển thị (Y-up) của viewer → hệ canonical (Z-up): nghịch đảo của (x, y, z) → (x, z, −y). */
export function displayToCanonical([x, y, z]: Vec3): Vec3 {
  return [x, -z, y];
}

/** Lấy đều tối đa `limit` đỉnh để làm bao lồi. */
export function sampleHull(points: Float32Array, limit = MAX_HULL_POINTS): Float32Array {
  const count = points.length / 3;
  if (count <= limit) return points;
  const result = new Float32Array(limit * 3);
  for (let i = 0; i < limit; i += 1) {
    const source = Math.floor((i * count) / limit) * 3;
    result.set(points.subarray(source, source + 3), i * 3);
  }
  return result;
}

/** Hộp bao (hệ canonical) chứa mọi vật động, nới thêm `margin`. */
function objectBounds(objects: readonly PhysicsObjectSpec[], margin: number): { min: Vec3; max: Vec3 } {
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const item of objects) {
    for (let axis = 0; axis < 3; axis += 1) {
      min[axis] = Math.min(min[axis], item.position[axis] - margin);
      max[axis] = Math.max(max[axis], item.position[axis] + margin);
    }
  }
  return { min, max };
}

/** Tam giác của lưới tĩnh có trọng tâm nằm trong vùng quanh vật động (giảm thời gian dựng cây va chạm). */
export function nearbyTriangles(mesh: TriangleMesh, objects: readonly PhysicsObjectSpec[], radius = ENVIRONMENT_RADIUS_M): number[] {
  const { min, max } = objectBounds(objects, radius);
  const kept: number[] = [];
  const { positions, indices } = mesh;
  for (let t = 0; t + 2 < indices.length; t += 3) {
    let inside = true;
    for (let axis = 0; axis < 3 && inside; axis += 1) {
      const centre = (positions[indices[t] * 3 + axis] + positions[indices[t + 1] * 3 + axis] + positions[indices[t + 2] * 3 + axis]) / 3;
      inside = centre >= min[axis] && centre <= max[axis];
    }
    if (inside) kept.push(t);
  }
  return kept;
}

export class ScenePhysics {
  private readonly A: AmmoModule;
  private readonly world: AmmoObject;
  private readonly owned: AmmoObject[] = [];
  private readonly bodies = new Map<string, { body: AmmoObject; initial: Pose }>();
  private readonly character: AmmoObject;
  private readonly scratch: AmmoObject;
  private readonly vector: AmmoObject;
  private readonly quaternion: AmmoObject;

  /** `environment`: lưới tĩnh ở hệ canonical (đã khoét vùng gốc của vật động). */
  constructor(ammo: AmmoModule, environment: TriangleMesh | null, objects: readonly PhysicsObjectSpec[]) {
    const A = ammo;
    this.A = A;
    const config = this.keep(new A.btDefaultCollisionConfiguration());
    const dispatcher = this.keep(new A.btCollisionDispatcher(config));
    const broadphase = this.keep(new A.btDbvtBroadphase());
    const solver = this.keep(new A.btSequentialImpulseConstraintSolver());
    this.world = this.keep(new A.btDiscreteDynamicsWorld(dispatcher, broadphase, solver, config));
    this.world.setGravity(this.keep(new A.btVector3(0, 0, -9.81)));
    this.scratch = this.keep(new A.btTransform());
    this.vector = this.keep(new A.btVector3(0, 0, 0));
    this.quaternion = this.keep(new A.btQuaternion(0, 0, 0, 1));
    this.addStatic(this.keep(new A.btStaticPlaneShape(this.keep(new A.btVector3(0, 0, 1)), 0)));
    if (environment && objects.length) {
      const triangles = nearbyTriangles(environment, objects);
      if (triangles.length) {
        const mesh = this.keep(new A.btTriangleMesh(true, true));
        const [a, b, c] = [this.keep(new A.btVector3()), this.keep(new A.btVector3()), this.keep(new A.btVector3())];
        const { positions, indices } = environment;
        for (const t of triangles) {
          for (const [vector, corner] of [[a, 0], [b, 1], [c, 2]] as const) {
            const i = indices[t + corner] * 3;
            vector.setValue(positions[i], positions[i + 1], positions[i + 2]);
          }
          mesh.addTriangle(a, b, c, false);
        }
        this.addStatic(this.keep(new A.btBvhTriangleMeshShape(mesh, true, true)));
      }
    }
    for (const item of objects) this.addDynamic(item);
    const capsule = this.keep(new A.btCapsuleShapeZ(CHARACTER_RADIUS_M, CHARACTER_HEIGHT_M - 2 * CHARACTER_RADIUS_M));
    this.character = this.body(0, capsule, { position: [0, 0, -100], rotation_xyzw: [0, 0, 0, 1] });
    this.character.setCollisionFlags(this.character.getCollisionFlags() | CF_KINEMATIC_OBJECT);
    this.character.setActivationState(DISABLE_DEACTIVATION);
    this.world.addRigidBody(this.character);
  }

  /**
   * Một bước mô phỏng. `feet`: vị trí chân người đi (hệ canonical) hoặc null khi không đi bộ (thân người đi rời khỏi
   * scene). Trả pose hiện tại của mọi vật động.
   */
  step(dt: number, feet: Vec3 | null): Map<string, Pose> {
    const centre = feet ? [feet[0], feet[1], feet[2] + CHARACTER_HEIGHT_M / 2] : [0, 0, -100];
    this.scratch.setIdentity();
    this.vector.setValue(centre[0], centre[1], centre[2]);
    this.scratch.setOrigin(this.vector);
    this.character.getMotionState().setWorldTransform(this.scratch);
    this.world.stepSimulation(Math.min(Math.max(dt, 0), 0.1), 6, 1 / 120);
    const poses = new Map<string, Pose>();
    for (const [id, { body }] of this.bodies) {
      body.getMotionState().getWorldTransform(this.scratch);
      const origin = this.scratch.getOrigin();
      const rotation = this.scratch.getRotation();
      poses.set(id, {
        position: [origin.x(), origin.y(), origin.z()],
        rotation_xyzw: [rotation.x(), rotation.y(), rotation.z(), rotation.w()],
      });
    }
    return poses;
  }

  /** Mọi vật về pose của SceneIR, đứng yên. */
  reset(): void {
    for (const { body, initial } of this.bodies.values()) {
      this.scratch.setIdentity();
      this.vector.setValue(...initial.position);
      this.scratch.setOrigin(this.vector);
      this.quaternion.setValue(...initial.rotation_xyzw);
      this.scratch.setRotation(this.quaternion);
      body.setWorldTransform(this.scratch);
      body.getMotionState().setWorldTransform(this.scratch);
      this.vector.setValue(0, 0, 0);
      body.setLinearVelocity(this.vector);
      body.setAngularVelocity(this.vector);
      body.activate();
    }
  }

  destroy(): void {
    for (const item of this.owned.reverse()) this.A.destroy(item);
    this.owned.length = 0;
    this.bodies.clear();
  }

  private keep<T extends AmmoObject>(object: T): T {
    this.owned.push(object);
    return object;
  }

  private transform(pose: Pose): AmmoObject {
    const A = this.A;
    const transform = this.keep(new A.btTransform());
    transform.setIdentity();
    transform.setOrigin(this.keep(new A.btVector3(...pose.position)));
    transform.setRotation(this.keep(new A.btQuaternion(...pose.rotation_xyzw)));
    return transform;
  }

  private body(mass: number, shape: AmmoObject, pose: Pose): AmmoObject {
    const A = this.A;
    const inertia = this.keep(new A.btVector3(0, 0, 0));
    if (mass > 0) shape.calculateLocalInertia(mass, inertia);
    const motion = this.keep(new A.btDefaultMotionState(this.transform(pose)));
    const info = this.keep(new A.btRigidBodyConstructionInfo(mass, motion, shape, inertia));
    return this.keep(new A.btRigidBody(info));
  }

  private addStatic(shape: AmmoObject): void {
    const body = this.body(0, shape, { position: [0, 0, 0], rotation_xyzw: [0, 0, 0, 1] });
    body.setFriction(0.8);
    this.world.addRigidBody(body);
  }

  private addDynamic(item: PhysicsObjectSpec): void {
    const A = this.A;
    let shape: AmmoObject;
    if (item.hull && item.hull.length >= 12) {
      shape = this.keep(new A.btConvexHullShape());
      const point = this.keep(new A.btVector3());
      const hull = sampleHull(item.hull);
      for (let i = 0; i < hull.length; i += 3) {
        point.setValue(hull[i], hull[i + 1], hull[i + 2]);
        shape.addPoint(point, i + 3 >= hull.length);
      }
    } else if (item.dimensions) {
      const [x, y, z] = item.dimensions;
      shape = this.keep(new A.btBoxShape(this.keep(new A.btVector3(x / 2, y / 2, z / 2))));
    } else {
      return;
    }
    shape.setMargin(0.01);
    const initial: Pose = { position: item.position, rotation_xyzw: item.rotation_xyzw };
    const body = this.body(Math.max(item.mass_kg, 0.1), shape, initial);
    body.setFriction(item.friction);
    body.setRestitution(item.restitution);
    body.setDamping(0.05, 0.2);
    this.world.addRigidBody(body);
    this.bodies.set(item.id, { body, initial });
  }
}

let loading: Promise<AmmoModule> | null = null;

/** Nạp ammo.js (WebAssembly, ~1,2 MB) một lần cho cả trang, chỉ khi người dùng bật tương tác vật lý. */
export function loadAmmo(base = "/vendor/ammo/"): Promise<AmmoModule> {
  loading ??= new Promise<AmmoModule>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${base}ammo.wasm.js`;
    script.async = true;
    script.onload = () => {
      const factory = (window as unknown as { Ammo?: (options: object) => Promise<AmmoModule> }).Ammo;
      if (!factory) return reject(new Error("ammo.js không khởi tạo được"));
      factory({ locateFile: (file: string) => `${base}${file}` }).then(resolve, reject);
    };
    script.onerror = () => reject(new Error("Không tải được ammo.js"));
    document.head.appendChild(script);
  }).catch((error: unknown) => {
    loading = null;
    throw error;
  });
  return loading;
}
