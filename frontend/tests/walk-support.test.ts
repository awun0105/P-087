// @vitest-environment node
import {expect,it} from "vitest";
import {createMeshCollision,isWalkStepSupported} from "@playcanvas/supersplat-viewer/viewer";

it("blocks a missing floor footprint while allowing a real floor and a 20cm step", () => {
  const mesh=createMeshCollision(new Float32Array([-2,0,-2,2,0,-2,2,0,2,-2,0,2]),new Uint32Array([0,1,2,0,2,3]));
  expect(isWalkStepSupported(mesh,0,0,0,.2)).toBe(true);
  expect(isWalkStepSupported(mesh,2.1,0,0,.2)).toBe(false);
  expect(isWalkStepSupported(mesh,0,.2,0,.2)).toBe(true);
  expect(isWalkStepSupported(mesh,0,1,0,.2)).toBe(false);
});

it("the installed WalkController restores the prior pose when a step has no supporting mesh", async () => {
  const {readFileSync}=await import("node:fs");
  const {runInNewContext}=await import("node:vm");
  const {Vec3,math}=await import("playcanvas");
  const source=readFileSync(new URL("../node_modules/@playcanvas/supersplat-viewer/dist/viewer.js",import.meta.url),"utf8");
  const start=source.indexOf("    _step(dt, move) {");
  const step=source.slice(start,source.indexOf("\n    onExit(_camera)",start));
  expect(step).toContain("REAL2SIM_WALK_SUPPORT");
  const collision=createMeshCollision(new Float32Array([-1,0,-1,1,0,-1,1,0,1,-1,0,1]),new Uint32Array([0,1,2,0,2,3]));
  collision.preventUnsupportedWalk=true;
  const host={_pendingCollision:null,_position:new Vec3(0,1.3,0),_velocity:new Vec3(2,0,0),_angles:{y:0},_probeGround:()=>0,_checkCollision:()=>{},collision,capsuleRadius:.2,eyeHeight:1.3,hoverHeight:0,springStiffness:0,springDamping:0,gravity:9.81,velocityDampingGround:0,velocityDampingAir:0,moveGroundSpeed:0,moveAirSpeed:0,_grounded:true,_jumping:false,_jumpHeld:false};
  const fn=runInNewContext(`({${step}})._step`,{Vec3,math,isWalkStepSupported,setYawBasis:()=>{},setBasisOffset:()=>{},forward:new Vec3(),right$1:new Vec3(),offset:new Vec3(),v:new Vec3(),d:new Vec3(),damp:()=>0});
  fn.call(host,1,[0,0,0]);
  expect(host._position.toArray()).toEqual([0,1.3,0]);
  expect(host._velocity.toArray()).toEqual([0,0,0]);
  collision.preventUnsupportedWalk=false;
  host._velocity.set(2,0,0);
  fn.call(host,1,[0,0,0]);
  expect(host._position.x).toBe(2);
});
