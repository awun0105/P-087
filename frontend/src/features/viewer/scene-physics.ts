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
import type { ColliderMeshPart, TriangleMesh } from "@/features/viewer/glb-mesh";

type Quat = [number, number, number, number];

/* eslint-disable @typescript-eslint/no-explicit-any -- ammo.js là binding WebAssembly không có kiểu; mọi lời gọi
   tới nó nằm gọn trong file này và chỉ dùng các lớp đã kiểm trong test vật lý. */
export type AmmoModule = any;
type AmmoObject = any;
/* eslint-enable @typescript-eslint/no-explicit-any */

export interface PhysicsObjectSpec {
  id: string;
  dynamic?: boolean;
  colliderType?: string;
  parts?: readonly ColliderMeshPart[];
  colliderLocalTransform?: { translation_xyz: Vec3; rotation_quaternion_xyzw: Quat } | null;
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
const CF_KINEMATIC_OBJECT = 2;
const DISABLE_DEACTIVATION = 4;

/** Không gian hiển thị (Y-up) của viewer → hệ canonical (Z-up): nghịch đảo của (x, y, z) → (x, z, −y). */
export function displayToCanonical([x, y, z]: Vec3): Vec3 {
  return [x, -z, y];
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
  private readonly worldBodies: AmmoObject[] = [];
  private destroyed = false;
  private readonly character: AmmoObject;
  private readonly scratch: AmmoObject;
  private readonly vector: AmmoObject;
  private readonly quaternion: AmmoObject;

  /** `environment`: lưới tĩnh ở hệ canonical (đã khoét vùng gốc của vật động). */
  constructor(ammo: AmmoModule, environment: TriangleMesh | null, objects: readonly PhysicsObjectSpec[]) {
    const A = ammo;
    this.A = A;
    try {
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
    if (new Set(objects.map(item => item.id)).size !== objects.length) throw new Error("Duplicate physics object IDs");
    for (const item of objects) this.addObject(item);
    const capsule = this.keep(new A.btCapsuleShapeZ(CHARACTER_RADIUS_M, CHARACTER_HEIGHT_M - 2 * CHARACTER_RADIUS_M));
    this.character = this.body(0, capsule, { position: [0, 0, -100], rotation_xyzw: [0, 0, 0, 1] });
    this.character.setCollisionFlags(this.character.getCollisionFlags() | CF_KINEMATIC_OBJECT);
    this.character.setActivationState(DISABLE_DEACTIVATION);
    this.registerBody(this.character);
    } catch (error: unknown) {
      this.destroy();
      throw error;
    }
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

  get statistics(): { objectBodies: number; worldBodies: number; ownedAllocations: number } {
    return { objectBodies: this.bodies.size, worldBodies: this.worldBodies.length, ownedAllocations: this.owned.length };
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    for (const body of this.worldBodies) this.world.removeRigidBody(body);
    this.worldBodies.length = 0;
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
    this.registerBody(body);
  }

  private registerBody(body: AmmoObject): void {
    this.world.addRigidBody(body);
    this.worldBodies.push(body);
  }

  private convex(points: Float32Array): AmmoObject {
    const vertices = convexHullVertices(points);
    const shape = this.keep(new this.A.btConvexHullShape());
    shape.setMargin(0.01);
    const point = this.keep(new this.A.btVector3());
    for (let i = 0; i < vertices.length; i += 3) {
      point.setValue(vertices[i], vertices[i+1], vertices[i+2]);
      shape.addPoint(point, i+3 === vertices.length);
    }
    return shape;
  }

  private triangleShape(meshes: readonly ColliderMeshPart[]): AmmoObject {
    const mesh = this.keep(new this.A.btTriangleMesh(true, true));
    const vectors = [0,1,2].map(() => this.keep(new this.A.btVector3()));
    for (const part of meshes) {
      validateTriangleMesh(part);
      for (let i = 0; i < part.indices.length; i += 3) {
        for (let corner = 0; corner < 3; corner += 1) {
          const index = part.indices[i+corner]*3;
          vectors[corner].setValue(part.positions[index], part.positions[index+1], part.positions[index+2]);
        }
        mesh.addTriangle(...vectors, false);
      }
    }
    return this.keep(new this.A.btBvhTriangleMeshShape(mesh, true, true));
  }

  private addObject(item: PhysicsObjectSpec): void {
    const transformError = physicsTransformBlocker(item);
    if (transformError) throw new Error(transformError);
    const dynamic = item.dynamic !== false;
    if (dynamic && (!Number.isFinite(item.mass_kg) || item.mass_kg <= 0)) throw new Error(`${item.id}: dynamic body requires positive authored mass`);
    const type = item.colliderType ?? (item.parts?.length || item.hull ? "CONVEX_HULL" : "AABB");
    let children: AmmoObject[];
    if (type === "AABB" || type === "OBB") {
      if (!item.dimensions || item.dimensions.some(value => !Number.isFinite(value) || value <= 0)) throw new Error(`${item.id}: box dimensions are invalid`);
      const half = this.keep(new this.A.btVector3(...item.dimensions.map(value => value/2)));
      const box = this.keep(new this.A.btBoxShape(half));
      box.setMargin(0.01);
      children = [box];
    } else if (type === "SIMPLIFIED_MESH") {
      if (dynamic) throw new Error(`${item.id}: dynamic concave triangle mesh is unsupported`);
      if (!item.parts?.length) throw new Error(`${item.id}: triangle collider has no parts`);
      children = [this.triangleShape(item.parts)];
    } else if (type === "CONVEX_HULL" || type === "CONVEX_DECOMPOSITION") {
      const parts = item.parts ?? (item.hull ? [{ positions: item.hull, indices: new Uint32Array() }] : []);
      if (!parts.length || (type === "CONVEX_HULL" && parts.length !== 1)) throw new Error(`${item.id}: collider part count does not match ${type}`);
      children = parts.map(part => this.convex(part.positions));
    } else throw new Error(`${item.id}: unsupported collider type ${type}`);
    // Compound created after its children so reverse teardown destroys parent before child shapes.
    const compound = this.keep(new this.A.btCompoundShape());
    compound.setMargin(0); // Only the child contact margin is applied; no second compound inflation.
    const local = item.colliderLocalTransform;
    const childTransform = this.transform({ position: local?.translation_xyz ?? [0,0,0], rotation_xyzw: local?.rotation_quaternion_xyzw ?? [0,0,0,1] });
    for (const child of children) compound.addChildShape(childTransform, child);
    const initial: Pose = { position: item.position, rotation_xyzw: item.rotation_xyzw };
    const body = this.body(dynamic ? item.mass_kg : 0, compound, initial);
    body.setFriction(item.friction);
    body.setRestitution(item.restitution);
    if (dynamic) body.setDamping(0.05, 0.2);
    this.registerBody(body);
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

/** Exact float32 duplicate removal, tolerance 0 metres; never subsample the boundary. */
export function convexHullVertices(points: Float32Array): Float32Array {
  if (points.length % 3 || !points.length) throw new Error("Convex part requires xyz vertices");
  const unique = new Map<string, number[]>();
  for (let i = 0; i < points.length; i += 3) {
    const p = [points[i], points[i+1], points[i+2]];
    if (!p.every(Number.isFinite)) throw new Error("Convex part has non-finite vertices");
    unique.set(p.join(","), p);
  }
  const vertices = [...unique.values()];
  if (vertices.length < 4) throw new Error("Convex part has fewer than four unique vertices");
  const p = vertices[0];
  const edges = vertices.slice(1).map(v => v.map((value, axis) => value-p[axis]));
  const length = (e: number[]) => Math.hypot(...e);
  const edge = edges.reduce((a,b) => length(a)>length(b)?a:b);
  const cross = (a: number[], b: number[]) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const normal = edges.map(e=>cross(edge,e)).reduce((a,b)=>length(a)>length(b)?a:b);
  let volume = 0;
  for (const e of edges) volume = Math.max(volume, Math.abs(e.reduce((sum,v,axis)=>sum+v*normal[axis],0)));
  if (volume <= Math.pow(length(edge),3)*1e-10) throw new Error("Convex part is degenerate/coplanar");
  return new Float32Array(vertices.flat());
}

export function validateTriangleMesh(mesh: ColliderMeshPart): void {
  const {positions,indices}=mesh;
  if (!positions.length || positions.length%3 || !indices.length || indices.length%3 || !positions.every(Number.isFinite)) throw new Error("Invalid triangle mesh arrays");
  for(let i=0;i<indices.length;i+=3) {
    const [a,b,c]=[indices[i],indices[i+1],indices[i+2]];
    if ([a,b,c].some(index=>index>=positions.length/3) || a===b || a===c || b===c) throw new Error("Invalid triangle mesh indices");
    const e1=[0,1,2].map(axis=>positions[b*3+axis]-positions[a*3+axis]);
    const e2=[0,1,2].map(axis=>positions[c*3+axis]-positions[a*3+axis]);
    const area=Math.hypot(e1[1]*e2[2]-e1[2]*e2[1],e1[2]*e2[0]-e1[0]*e2[2],e1[0]*e2[1]-e1[1]*e2[0]);
    if(!Number.isFinite(area)||area===0) throw new Error("Degenerate triangle mesh face");
  }
}


/** Verify that triangle surfaces and the convex hull represent the same closed volume. */
export function validateConvexPart(part: ColliderMeshPart): void {
  const vertices=convexHullVertices(part.positions);
  validateTriangleMesh(part);
  const unique=new Map<string,number>();
  const vertexIds:number[]=[];
  for(let i=0;i<part.positions.length;i+=3) {
    const key=Array.from(part.positions.subarray(i,i+3)).join(",");
    if(!unique.has(key))unique.set(key,unique.size);
    vertexIds.push(unique.get(key)!);
  }
  const edges=new Map<string,number>();
  const span=Math.max(...[0,1,2].map(axis=>{
    let low=Infinity,high=-Infinity;
    for(let i=axis;i<vertices.length;i+=3){low=Math.min(low,vertices[i]);high=Math.max(high,vertices[i]);}
    return high-low;
  }));
  const tolerance=span*1e-5;
  for(let i=0;i<part.indices.length;i+=3) {
    const ids=[part.indices[i],part.indices[i+1],part.indices[i+2]];
    for(let j=0;j<3;j++) {
      const a=vertexIds[ids[j]],b=vertexIds[ids[(j+1)%3]],key=a<b?`${a}:${b}`:`${b}:${a}`;
      edges.set(key,(edges.get(key)??0)+1);
    }
    const [a,b,c]=ids.map(id=>Array.from(part.positions.subarray(id*3,id*3+3)));
    const u=b.map((value,axis)=>value-a[axis]),v=c.map((value,axis)=>value-a[axis]);
    const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...n);
    let low=Infinity,high=-Infinity;
    for(let j=0;j<vertices.length;j+=3){const distance=n.reduce((sum,value,axis)=>sum+value*(vertices[j+axis]-a[axis]),0)/length;low=Math.min(low,distance);high=Math.max(high,distance);}
    if(low < -tolerance && high > tolerance)throw new Error("Declared convex part has a non-convex surface");
  }
  if([...edges.values()].some(count=>count!==2))throw new Error("Convex part surface is not closed/manifold");
}


export function physicsTransformBlocker(item: Pick<PhysicsObjectSpec, "id" | "position" | "rotation_xyzw" | "colliderLocalTransform">): string | null {
  const poses = [{ position: item.position, rotation: item.rotation_xyzw }];
  if (item.colliderLocalTransform) poses.push({ position: item.colliderLocalTransform.translation_xyz, rotation: item.colliderLocalTransform.rotation_quaternion_xyzw });
  if (poses.some(pose => pose.position.length !== 3 || !pose.position.every(Number.isFinite) || pose.rotation.length !== 4 || !pose.rotation.every(Number.isFinite) || Math.abs(Math.hypot(...pose.rotation) - 1) > 1e-6)) return `${item.id}: collider/object transform must be finite with a normalized xyzw quaternion`;
  return null;
}
