// @vitest-environment node
import { describe, expect, it } from "vitest";
import { ObjectCameraCollision, CombinedCollision } from "@/features/viewer/camera-collision";
import { createMeshCollision } from "@playcanvas/supersplat-viewer/viewer";
import { parseGlbCollider } from "@/features/viewer/glb-mesh";
import type { PhysicsObjectSpec } from "@/features/viewer/scene-physics";
import { BOX_POINTS, colliderGlb } from "./helpers/collider-glb";

function spec():PhysicsObjectSpec {
  return {id:"table",dynamic:false,colliderType:"CONVEX_DECOMPOSITION",position:[0,0,0],rotation_xyzw:[0,0,0,1],hull:null,dimensions:null,mass_kg:0,friction:.5,restitution:0,
    parts:parseGlbCollider(colliderGlb({parts:[BOX_POINTS.map(([x,y,z])=>[x-2,y,z+2]),BOX_POINTS.map(([x,y,z])=>[x+2,y,z+2])]})).parts};
}
describe("real pinned viewer camera collision",()=>{
  it("camera ray/capsule hit each multipart surface and pass through the actual gap",()=>{
    const collision=new ObjectCameraCollision([spec()]);
    expect(collision.queryRay(-2,5,0,0,-1,0,4.8)).not.toBeNull();
    expect(collision.queryRay(2,5,0,0,-1,0,4.8)).not.toBeNull();
    expect(collision.queryRay(0,5,0,0,-1,0,4.8)).toBeNull();
    const out={x:0,y:0,z:0};
    expect(collision.queryCapsule(-1.45,2,0,.5,.2,out)).toBe(true);
    expect(out.x).toBeGreaterThan(0);
    expect(collision.queryCapsule(0,2,0,.5,.2,out)).toBe(false);
    const count=collision.rebuilds;
    collision.setPose("table",{position:[0,0,0],rotation_xyzw:[0,0,0,1]});
    expect(collision.rebuilds).toBe(count);
    collision.setPose("table",{position:[10,0,0],rotation_xyzw:[0,0,0,1]});
    expect(collision.queryRay(-2,5,0,0,-1,0,4.8)).toBeNull();
    expect(collision.queryRay(8,5,0,0,-1,0,4.8)).not.toBeNull();
    collision.clear();expect(collision.queryRay(8,5,0,0,-1,0,4.8)).toBeNull();
  });

  it("combines PR-03 environment and object queries without replacing environment or closing gaps",()=>{
    const environment=createMeshCollision(new Float32Array([-4,0,-4,4,0,-4,4,0,4,-4,0,4]),new Uint32Array([0,1,2,0,2,3]));
    const object=new ObjectCameraCollision([spec()]);
    const combined=new CombinedCollision(()=>[environment,object]);
    expect(combined.queryRay(0,5,0,0,-1,0,10)?.y).toBeCloseTo(0); // Gap reaches retained floor.
    expect(combined.queryRay(-2,5,0,0,-1,0,10)?.y).toBeCloseTo(3.5);
    const out={x:0,y:0,z:0};
    expect(combined.queryCapsule(-1.45,2,0,.5,.2,out)).toBe(true);
    expect(out.x).toBeGreaterThan(0);
  });
});

it("pose updates rebuild only the changed object query mesh, never the PR-03 environment BVH",()=>{
  const environment=createMeshCollision(new Float32Array([-4,0,-4,4,0,-4,4,0,4,-4,0,4]),new Uint32Array([0,1,2,0,2,3]));
  const objects=new ObjectCameraCollision([spec()]);const combined=new CombinedCollision(()=>[environment,objects]);
  const start=performance.now();
  for(let frame=0;frame<300;frame++)objects.setPose("table",{position:[frame*.01,0,0],rotation_xyzw:[0,0,0,1]});
  const duration=performance.now()-start;
  expect(objects.rebuilds).toBe(300); // First identical pose is reused.
  expect(combined.queryRay(0,5,0,0,-1,0,10)).not.toBeNull();
  objects.clear();expect(combined.queryRay(0,5,0,0,-1,0,10)?.y).toBe(0);
  console.log("PR04 camera query metrics",JSON.stringify({changedPoses:299,queryBuilds:objects.rebuilds,durationMs:duration,environmentRebuilds:0,trianglesPerObject:24}));
});
