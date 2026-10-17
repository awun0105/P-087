/** Camera uses the same authored parts/current poses as Ammo, without rebuilding environment BVH. */
import { Mat4, Quat, Vec3 } from "playcanvas";
import { createMeshCollision, type CollisionQuery } from "@playcanvas/supersplat-viewer/viewer";
import { joinMeshParts, type TriangleMesh } from "@/features/viewer/glb-mesh";
import type { PhysicsObjectSpec, Pose } from "@/features/viewer/scene-physics";

export class CombinedCollision implements CollisionQuery {
  readonly preventUnsupportedWalk = true;
  private readonly push = { x: 0, y: 0, z: 0 };
  constructor(private readonly members: () => readonly CollisionQuery[], public voxelResolution = .05) {}
  queryRay(ox:number,oy:number,oz:number,dx:number,dy:number,dz:number,maxDist:number) {
    let nearest: {x:number;y:number;z:number}|null = null;
    let distance = Infinity;
    for (const member of this.members()) {
      const hit = member.queryRay(ox,oy,oz,dx,dy,dz,maxDist);
      if (!hit) continue;
      const d = Math.hypot(hit.x-ox,hit.y-oy,hit.z-oz);
      if (d < distance) { nearest=hit;distance=d; }
    }
    return nearest;
  }
  querySphere(cx:number,cy:number,cz:number,radius:number,out:{x:number;y:number;z:number}) {
    return this.resolve(cx,cy,cz,(m,x,y,z,p)=>m.querySphere(x,y,z,radius,p),out);
  }
  queryCapsule(cx:number,cy:number,cz:number,half:number,radius:number,out:{x:number;y:number;z:number}) {
    return this.resolve(cx,cy,cz,(m,x,y,z,p)=>m.queryCapsule(x,y,z,half,radius,p),out);
  }
  private resolve(cx:number,cy:number,cz:number,query:(m:CollisionQuery,x:number,y:number,z:number,out:{x:number;y:number;z:number})=>boolean,out:{x:number;y:number;z:number}):boolean {
    let x=cx,y=cy,z=cz,hit=false;
    // Revisit the union at corners: each member already performs its own iterative triangle resolution.
    for(let iteration=0;iteration<8;iteration++) {
      let pushed=false;
      for(const member of this.members()) {
        this.push.x=0;this.push.y=0;this.push.z=0;
        if(query(member,x,y,z,this.push)) { x+=this.push.x;y+=this.push.y;z+=this.push.z;pushed=true;hit=true; }
      }
      if(!pushed)break;
    }
    out.x=x-cx;out.y=y-cy;out.z=z-cz;return hit;
  }
  isFreeAt(x:number,y:number,z:number):boolean { return this.members().every(m=>m.isFreeAt(x,y,z)); }
  querySurfaceNormal(x:number,y:number,z:number,dx:number,dy:number,dz:number) {
    let chosen:CollisionQuery|null=null,distance=Infinity;
    for(const member of this.members()) {
      const hit=member.queryRay(x,y,z,dx,dy,dz,1);
      if(!hit)continue;
      const d=Math.hypot(hit.x-x,hit.y-y,hit.z-z);
      if(d<distance){chosen=member;distance=d;}
    }
    return chosen?.querySurfaceNormal(x,y,z,dx,dy,dz)??{nx:0,ny:1,nz:0};
  }
}

export function boxColliderMesh(dimensions: readonly number[]): TriangleMesh {
  const positions:number[]=[];
  for(const x of [-.5,.5])for(const y of [-.5,.5])for(const z of [-.5,.5])positions.push(x*dimensions[0],y*dimensions[1],z*dimensions[2]);
  return {positions:new Float32Array(positions),indices:new Uint32Array([0,4,6,0,6,2,1,3,7,1,7,5,0,1,5,0,5,4,2,6,7,2,7,3,0,2,3,0,3,1,4,5,7,4,7,6])};
}

export class ObjectCameraCollision extends CombinedCollision {
  private readonly shapes = new Map<string,{mesh:TriangleMesh;poseKey:string;collision:CollisionQuery}>();
  private readonly queries:CollisionQuery[]=[];
  rebuilds=0;
  constructor(objects:readonly PhysicsObjectSpec[]) {
    const members:CollisionQuery[]=[];
    super(()=>members);
    this.queries=members;
    for(const item of objects) {
      const type=item.colliderType??(item.parts?.length||item.hull?"CONVEX_HULL":"AABB");
      const raw=type==="AABB"||type==="OBB"?boxColliderMesh(item.dimensions!):joinMeshParts(item.parts!);
      const local=item.colliderLocalTransform;
      const mesh=local?transformMesh(raw,{position:local.translation_xyz,rotation_xyzw:local.rotation_quaternion_xyzw},false):raw;
      const pose={position:item.position,rotation_xyzw:item.rotation_xyzw};
      const world=transformMesh(mesh,pose,true);
      const collision=createMeshCollision(world.positions,world.indices);
      this.shapes.set(item.id,{mesh,poseKey:JSON.stringify(pose),collision});
      this.queries.push(collision);
      this.rebuilds++;
    }
  }
  setPose(id:string,pose:Pose):void {
    const shape=this.shapes.get(id);
    if(!shape)return;
    const key=JSON.stringify(pose);
    if(key===shape.poseKey)return;
    const mesh=transformMesh(shape.mesh,pose,true);
    shape.collision=createMeshCollision(mesh.positions,mesh.indices);
    shape.poseKey=key;
    this.queries.length=0;
    for(const entry of this.shapes.values())this.queries.push(entry.collision);
    this.rebuilds++;
  }
  clear():void { this.shapes.clear();this.queries.length=0; }
}

function transformMesh(mesh:TriangleMesh,pose:Pose,display:boolean):TriangleMesh {
  const matrix=new Mat4().setTRS(new Vec3(...pose.position),new Quat(...pose.rotation_xyzw),Vec3.ONE);
  const positions=new Float32Array(mesh.positions.length),point=new Vec3();
  for(let i=0;i<positions.length;i+=3) {
    matrix.transformPoint(point.set(mesh.positions[i],mesh.positions[i+1],mesh.positions[i+2]),point);
    positions.set(display?[point.x,point.z,-point.y]:[point.x,point.y,point.z],i);
  }
  return {positions,indices:mesh.indices};
}
