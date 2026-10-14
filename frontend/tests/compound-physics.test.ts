// @vitest-environment node
import { createRequire } from "node:module";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { ScenePhysics, convexHullVertices, type AmmoModule, type PhysicsObjectSpec } from "@/features/viewer/scene-physics";
import { parseGlbCollider } from "@/features/viewer/glb-mesh";
import { BOX_POINTS, colliderGlb } from "./helpers/collider-glb";

let A: AmmoModule;
beforeAll(async()=>{
  const dir=path.resolve(__dirname,"../public/vendor/ammo");
  A=await createRequire(import.meta.url)(path.join(dir,"ammo.wasm.js"))({locateFile:(file:string)=>path.join(dir,file)});
});
function item(overrides:Partial<PhysicsObjectSpec>={}):PhysicsObjectSpec {
  const left=BOX_POINTS.map(([x,y,z])=>[x-2,y,z+2] as [number,number,number]);
  const right=BOX_POINTS.map(([x,y,z])=>[x+2,y,z+2] as [number,number,number]);
  return {id:"table",dynamic:false,colliderType:"CONVEX_DECOMPOSITION",position:[0,0,0],rotation_xyzw:[0,0,0,1],parts:parseGlbCollider(colliderGlb({parts:[left,right]})).parts,hull:null,dimensions:null,mass_kg:12,friction:.6,restitution:.2,...overrides};
}
function body(physics:ScenePhysics):AmmoModule {
  return (physics as unknown as {bodies:Map<string,{body:AmmoModule}>}).bodies.get("table")!.body;
}
function ray(physics:ScenePhysics,from:number[],to:number[]):number[]|null {
  const a=new A.btVector3(...from),b=new A.btVector3(...to),callback=new A.ClosestRayResultCallback(a,b);
  try {
    (physics as unknown as {world:AmmoModule}).world.rayTest(a,b,callback);
    if(!callback.hasHit())return null;
    const p=callback.get_m_hitPointWorld();return[p.x(),p.y(),p.z()];
  }finally{A.destroy(callback);A.destroy(a);A.destroy(b);}
}

describe("real Ammo multipart/static colliders",()=>{
  it("hits each part, misses the gap and creates one static object body",()=>{
    const p=new ScenePhysics(A,null,[item()]);
    try{
      expect(p.statistics.objectBodies).toBe(1);
      expect(A.castObject(body(p).getCollisionShape(), A.btCompoundShape).getNumChildShapes()).toBe(2);
      expect(ray(p,[-2,0,5],[-2,0,.2])).not.toBeNull();
      expect(ray(p,[2,0,5],[2,0,.2])).not.toBeNull();
      expect(ray(p,[0,0,5],[0,0,.2])).toBeNull();
      expect(body(p).isStaticObject()).toBe(true);
      const force=new A.btVector3(100,0,0);body(p).applyCentralImpulse(force);A.destroy(force);
      let pose=p.step(0,null).get("table")!;
      for(let i=0;i<300;i++)pose=p.step(1/60,null).get("table")!;
      expect(pose.position).toEqual([0,0,0]);
    }finally{p.destroy();}
    expect(p.statistics).toEqual({objectBodies:0,worldBodies:0,ownedAllocations:0});
    p.destroy();
  });

  it("uses one dynamic body with authored mass and finite compound inertia",()=>{
    const constructions:{mass:number;inertia:number[]}[]=[];
    const tracked=new Proxy(A,{get:(target,key)=>key==="btRigidBodyConstructionInfo"?function(mass:number,motion:AmmoModule,shape:AmmoModule,inertia:AmmoModule){
      constructions.push({mass,inertia:[inertia.x(),inertia.y(),inertia.z()]});
      return new target.btRigidBodyConstructionInfo(mass,motion,shape,inertia);
    }:target[key]});
    const p=new ScenePhysics(tracked,null,[item({dynamic:true,position:[0,0,5]})]);
    try{
      expect(p.statistics.objectBodies).toBe(1);
      const info=constructions.find(v=>v.mass>0)!;
      expect(info.mass).toBe(12);expect(info.inertia.every(v=>Number.isFinite(v)&&v>0)).toBe(true);
      const initial=p.step(0,null).get("table")!.position[2];
      const after=p.step(.1,null).get("table")!.position[2];expect(after).toBeLessThan(initial);
      expect(body(p).getFriction()).toBeCloseTo(.6);expect(body(p).getRestitution()).toBeCloseTo(.2);
      expect(A.castObject(body(p).getCollisionShape(), A.btCompoundShape).getNumChildShapes()).toBe(2);
    }finally{p.destroy();}
  });

  it("supports static triangle meshes and refuses dynamic concave meshes",()=>{
    const p=new ScenePhysics(A,null,[item({colliderType:"SIMPLIFIED_MESH"})]);
    try{expect(ray(p,[-2,0,5],[-2,0,.2])).not.toBeNull();expect(ray(p,[0,0,5],[0,0,.2])).toBeNull();}finally{p.destroy();}
    expect(()=>new ScenePhysics(A,null,[item({colliderType:"SIMPLIFIED_MESH",dynamic:true})])).toThrow(/dynamic concave/);
  });

  it("deduplicates only exact vertices and retains more than 256 boundary points",()=>{
    const sphere:number[]=[];
    for(let i=0;i<1024;i++){
      const z=1-2*(i+.5)/1024;const angle=i*Math.PI*(3-Math.sqrt(5));const r=Math.sqrt(1-z*z);
      sphere.push(r*Math.cos(angle),r*Math.sin(angle),z);
    }
    const points=convexHullVertices(new Float32Array([...sphere,...sphere]));expect(points.length/3).toBe(1024);
    const p=new ScenePhysics(A,null,[item({colliderType:"CONVEX_HULL",parts:[{positions:points,indices:new Uint32Array()}]})]);
    try{expect(A.castObject(body(p).getCollisionShape(), A.btCompoundShape).getNumChildShapes()).toBe(1);expect(ray(p,[0,0,2],[0,0,.2])).not.toBeNull();}finally{p.destroy();}
    expect(()=>convexHullVertices(new Float32Array([0,0,0,1,0,0,0,1,0,1,1,0]))).toThrow(/degenerate/);
    expect(()=>convexHullVertices(new Float32Array([0,0,0,1,0,0,0,1,0,0,0,NaN]))).toThrow(/finite/);
  });
});

it("matches canonical object × collider × GLB-node transforms in Ammo and camera queries", async()=>{
  const { ObjectCameraCollision }=await import("@/features/viewer/camera-collision");
  const parts=parseGlbCollider(colliderGlb({edit:doc=>{
    doc.nodes[0].translation=[-1,2,0];delete doc.nodes[1].matrix;
    doc.nodes[1].translation=[2,0,.5];doc.nodes[1].rotation=[0,0,Math.SQRT1_2,Math.SQRT1_2];
  }})).parts;
  const object=item({colliderType:"CONVEX_HULL",parts,position:[10,20,3],rotation_xyzw:[0,0,Math.SQRT1_2,Math.SQRT1_2],colliderLocalTransform:{translation_xyz:[3,-1,.5],rotation_quaternion_xyzw:[0,0,Math.SQRT1_2,Math.SQRT1_2]}});
  const p=new ScenePhysics(A,null,[object]);const camera=new ObjectCameraCollision([object]);
  const min=new A.btVector3(),max=new A.btVector3();
  try{
    const hit=ray(p,[7,21,4],[15,21,4]);expect(hit).not.toBeNull();expect(hit![0]).toBeCloseTo(9,1);
    const cameraHit=camera.queryRay(7,4,-21,1,0,0,8)!;expect(cameraHit.x).toBeCloseTo(9,4);expect(cameraHit.y).toBeCloseTo(hit![2],4);expect(-cameraHit.z).toBeCloseTo(hit![1],4);
    body(p).getAabb(min,max);
    [min.x(),min.y(),min.z()].forEach((value,axis)=>expect(value).toBeCloseTo([9,20.5,2.5][axis],1));
    [max.x(),max.y(),max.z()].forEach((value,axis)=>expect(value).toBeCloseTo([11,21.5,5.5][axis],1));
    expect(ray(p,[-3,0,4],[5,0,4])).toBeNull();
    expect(p.step(0,null).get("table")!.position).toEqual([10,20,3]); // Gaussian/object pose stays distinct from child center.
  }finally{A.destroy(min);A.destroy(max);p.destroy();camera.clear();}
});

it("repeated native world teardown balances tracked allocations and stabilizes WASM heap capacity",()=>{
  const live=new Set<number>();let allocations=0,releases=0;
  const tracked=new Proxy(A,{get:(target,key)=>{
    if(key==="destroy")return (object:AmmoModule)=>{const pointer=A.getPointer(object);expect(live.delete(pointer)).toBe(true);releases++;target.destroy(object);};
    const value=target[key];
    if(typeof key==="string"&&key.startsWith("bt")&&typeof value==="function")return function(...args:unknown[]){const object=new value(...args);live.add(A.getPointer(object));allocations++;return object;};
    return value;
  }});
  const environment={positions:new Float32Array([-10,-10,0,10,-10,0,10,10,0,-10,10,0]),indices:new Uint32Array([0,1,2,0,2,3])};
  const run=()=>{const p=new ScenePhysics(tracked,environment,[item(),item({id:"dynamic",dynamic:true,position:[5,0,4]})]);for(let frame=0;frame<30;frame++)p.step(1/60,null);p.reset();p.destroy();expect(p.statistics.ownedAllocations).toBe(0);expect(live.size).toBe(0);};
  for(let i=0;i<5;i++)run();
  const before=A.HEAP8.byteLength,start=performance.now();
  for(let i=0;i<50;i++)run();
  const duration=performance.now()-start,after=A.HEAP8.byteLength;
  expect(allocations).toBe(releases);expect(after).toBe(before);
  console.log("PR04 native allocation metrics",JSON.stringify({cycles:55,allocations,releases,live:live.size,heapBefore:before,heapAfter:after,measuredCycles:50,durationMs:duration}));
});

it("rejecting invalid dynamic geometry also releases the partially constructed native world",()=>{
  const live=new Set<number>();
  const tracked=new Proxy(A,{get:(target,key)=>{
    if(key==="destroy")return(object:AmmoModule)=>{expect(live.delete(A.getPointer(object))).toBe(true);target.destroy(object);};
    const value=target[key];
    if(typeof key==="string"&&key.startsWith("bt")&&typeof value==="function")return function(...args:unknown[]){const object=new value(...args);live.add(A.getPointer(object));return object;};
    return value;
  }});
  expect(()=>new ScenePhysics(tracked,null,[item({dynamic:true,mass_kg:0})])).toThrow(/authored mass/);
  expect(live.size).toBe(0);
  expect(()=>new ScenePhysics(tracked,null,[item({parts:[{positions:new Float32Array([0,0,0,1,0,0,0,1,0,1,1,0]),indices:new Uint32Array()}]})])).toThrow(/degenerate/);
  expect(live.size).toBe(0);
});
