import { describe, expect, it } from "vitest";

import { parseGlbMesh } from "@/features/viewer/glb-mesh";
import { BOX_POINTS, colliderGlb, type GlbFixtureDocument } from "./helpers/collider-glb";

describe("baked physics GLB layout", () => {
  it("keeps the exact canonical vertices and rebases indices of each multipart mesh", () => {
    const other = BOX_POINTS.map(([x, y, z]) => [x + 4, y - 2, z + 1] as [number, number, number]);
    const mesh = parseGlbMesh(colliderGlb({ parts: [BOX_POINTS, other] }));
    expect(Array.from(mesh.positions)).toEqual([...BOX_POINTS, ...other].flat());
    expect(Array.from(mesh.indices.slice(36))).toEqual(Array.from(mesh.indices.slice(0, 36), (index) => index + 8));
  });

  it.each<[string, (document: GlbFixtureDocument) => void]>([
    ["matrix translation", (doc) => { doc.nodes[1].matrix![12] = 2; }],
    ["TRS rotation", (doc) => { delete doc.nodes[1].matrix; doc.nodes[1].rotation = [0, 0, Math.SQRT1_2, Math.SQRT1_2]; }],
    ["parent translation", (doc) => { doc.nodes[0].translation = [0, 1, 0]; }],
    ["node scale", (doc) => { doc.nodes[0].scale = [1, 2, 1]; }],
    ["mixed matrix/TRS", (doc) => { doc.nodes[1].translation = [0, 0, 0]; }],
    ["instanced mesh", (doc) => { doc.nodes.push({ mesh: 0 }); doc.nodes[0].children!.push(2); }],
    ["cycle", (doc) => { doc.nodes[1].children = [0]; }],
    ["unbound mesh", (doc) => { doc.nodes[0].children = []; }],
    ["skin", (doc) => { doc.nodes[1].skin = 0; }],
    ["morph target", (doc) => { doc.meshes[0].primitives[0].targets = [{}]; }],
    ["sparse POSITION", (doc) => { doc.accessors[0].sparse = { count: 1 }; }],
    ["external buffer", (doc) => { doc.buffers[0].uri = "external.bin"; }],
    ["non-triangle primitive", (doc) => { doc.meshes[0].primitives[0].mode = 1; }],
    ["POSITION range", (doc) => { doc.accessors[0].count = 999; }],
    ["index range", (doc) => { doc.accessors[1].count = 999; }],
    ["interleaved indices", (doc) => { doc.bufferViews[1].byteStride = 8; }],
  ])("rejects %s with an explicit GLB error", (_name, edit) => {
    expect(() => parseGlbMesh(colliderGlb({ edit }))).toThrow(/GLB/);
  });

  it("accepts explicitly identity TRS nodes without changing points", () => {
    const mesh = parseGlbMesh(colliderGlb({ edit: (doc) => {
      delete doc.nodes[1].matrix;
      doc.nodes[1].translation = [0, 0, 0]; doc.nodes[1].rotation = [0, 0, 0, -1]; doc.nodes[1].scale = [1, 1, 1];
    } }));
    expect(Array.from(mesh.positions)).toEqual(BOX_POINTS.flat());
  });

  it("rejects truncated data instead of accepting a shorter index array", () => {
    const buffer = colliderGlb();
    expect(() => parseGlbMesh(buffer.slice(0, -4))).toThrow(/GLB/);
  });

  it("rejects non-finite coordinates", () => {
    expect(() => parseGlbMesh(colliderGlb({ parts: [[[NaN, 0, 0], ...BOX_POINTS.slice(1)]] }))).toThrow(/GLB/);
  });

  it("rejects triangle indices outside the part's vertices", () => {
    const buffer = colliderGlb();
    const bytes = new DataView(buffer);
    const binaryStart = 28 + bytes.getUint32(12, true);
    bytes.setUint32(binaryStart + BOX_POINTS.length * 12, 99, true);
    expect(() => parseGlbMesh(buffer)).toThrow(/indices/);
  });
});
