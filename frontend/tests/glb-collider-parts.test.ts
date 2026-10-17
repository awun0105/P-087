import { describe, expect, it } from "vitest";
import { parseGlbCollider, parseGlbMesh } from "@/features/viewer/glb-mesh";
import { colliderGlb, BOX_POINTS } from "./helpers/collider-glb";

describe("canonical multipart collider parser", () => {
  it("keeps disjoint primitive parts and their own indices", () => {
    const other = BOX_POINTS.map(([x,y,z]) => [x+4,y,z] as [number,number,number]);
    const parsed = parseGlbCollider(colliderGlb({parts:[BOX_POINTS,other]}));
    expect(parsed.parts).toHaveLength(2);
    expect(Array.from(parsed.parts[0].positions)).toEqual(BOX_POINTS.flat());
    expect(Array.from(parsed.parts[1].positions)).toEqual(other.flat());
    expect(Array.from(parsed.parts[1].indices)).toEqual(Array.from(parsed.parts[0].indices));
  });

  it("bakes nested node translation, rotation and scale once, with canonical axes unchanged", () => {
    const buffer = colliderGlb({edit:doc => {
      doc.nodes[0].translation=[10,20,30];
      delete doc.nodes[1].matrix;
      doc.nodes[1].translation=[2,-1,.5];
      doc.nodes[1].rotation=[0,0,Math.SQRT1_2,Math.SQRT1_2];
      doc.nodes[1].scale=[1,2,3];
    }});
    const parsed=parseGlbCollider(buffer);
    parsed.parts[0].positions.forEach((v,i) => expect(v).toBeCloseTo(BOX_POINTS.flatMap(([x,y,z])=>[12-2*y,19+x,30.5+3*z])[i],5));
    expect(()=>parseGlbMesh(buffer)).toThrow(/node transform/); // Environment still requires baked identity nodes.
  });

  it("preserves repeated mesh instances as separate children", () => {
    const parsed=parseGlbCollider(colliderGlb({edit:doc=>{
      doc.nodes.push({mesh:0,translation:[4,0,0]});doc.nodes[0].children!.push(2);
    }}));
    expect(parsed.parts).toHaveLength(2);
    expect(parsed.parts[1].positions[0]).toBe(3.5);
  });

  it.each(["singular","cycle","matrix-trs","non-affine"])("rejects unsupported %s instead of guessing", fault=>{
    expect(()=>parseGlbCollider(colliderGlb({edit:doc=>{
      if(fault==="singular")doc.nodes[0].scale=[1,0,1];
      if(fault==="cycle")doc.nodes[1].children=[0];
      if(fault==="matrix-trs")doc.nodes[1].translation=[1,0,0];
      if(fault==="non-affine")doc.nodes[1].matrix![3]=.1;
    }}))).toThrow(/GLB/);
  });
});
