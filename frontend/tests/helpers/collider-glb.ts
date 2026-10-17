import { toDisplay, type Vec3 } from "@/features/viewer/source-frame";

export interface GlbFixtureDocument {
  asset: { version: string };
  buffers: { byteLength: number; uri?: string }[];
  bufferViews: { buffer: number; byteOffset: number; byteLength: number; byteStride?: number }[];
  accessors: { bufferView: number; componentType: number; count: number; type: string; sparse?: object }[];
  meshes: { primitives: { attributes: { POSITION: number }; indices: number; mode?: number; targets?: object[] }[] }[];
  nodes: { name?: string; mesh?: number; children?: number[]; matrix?: number[]; translation?: number[]; rotation?: number[]; scale?: number[]; skin?: number }[];
  scenes: { nodes: number[] }[];
  scene: number;
}

export const BOX_POINTS: Vec3[] = [
  [-0.5, -1, -1.5], [-0.5, -1, 1.5], [-0.5, 1, -1.5], [-0.5, 1, 1.5],
  [0.5, -1, -1.5], [0.5, -1, 1.5], [0.5, 1, -1.5], [0.5, 1, 1.5],
];
const FACES = [0, 4, 6, 0, 6, 2, 1, 3, 7, 1, 7, 5, 0, 1, 5, 0, 5, 4,
  2, 6, 7, 2, 7, 3, 0, 2, 3, 0, 3, 1, 4, 5, 7, 4, 7, 6];

/** Fixture cùng layout Scene GLB của trimesh: các part có đỉnh đã bake, node identity. */
export function colliderGlb({
  parts = [BOX_POINTS],
  frame = "canonical",
  edit,
}: {
  parts?: Vec3[][];
  frame?: "canonical" | "display";
  edit?: (document: GlbFixtureDocument) => void;
} = {}): ArrayBuffer {
  const document: GlbFixtureDocument = {
    asset: { version: "2.0" }, buffers: [{ byteLength: 0 }], bufferViews: [], accessors: [], meshes: [],
    nodes: [{ name: "world", children: parts.map((_, i) => i + 1) }], scenes: [{ nodes: [0] }], scene: 0,
  };
  const binary = new Uint8Array(parts.length * (BOX_POINTS.length * 12 + FACES.length * 4));
  const data = new DataView(binary.buffer);
  let offset = 0;
  for (const [index, points] of parts.entries()) {
    const positionView = document.bufferViews.length;
    document.bufferViews.push({ buffer: 0, byteOffset: offset, byteLength: points.length * 12 });
    for (const point of points) {
      for (const value of frame === "display" ? toDisplay("z_up", point) : point) {
        data.setFloat32(offset, value, true);
        offset += 4;
      }
    }
    const indicesView = document.bufferViews.length;
    document.bufferViews.push({ buffer: 0, byteOffset: offset, byteLength: FACES.length * 4 });
    for (const value of FACES) { data.setUint32(offset, value, true); offset += 4; }
    const positionAccessor = document.accessors.length;
    document.accessors.push({ bufferView: positionView, componentType: 5126, count: points.length, type: "VEC3" });
    const indicesAccessor = document.accessors.length;
    document.accessors.push({ bufferView: indicesView, componentType: 5125, count: FACES.length, type: "SCALAR" });
    document.meshes.push({ primitives: [{ attributes: { POSITION: positionAccessor }, indices: indicesAccessor }] });
    document.nodes.push({ name: `part_${index}`, mesh: index, matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] });
  }
  document.buffers[0].byteLength = binary.length;
  edit?.(document);
  const json = new TextEncoder().encode(JSON.stringify(document));
  const paddedLength = (json.length + 3) & ~3;
  const result = new ArrayBuffer(28 + paddedLength + binary.length);
  const header = new DataView(result);
  header.setUint32(0, 0x46546c67, true); header.setUint32(4, 2, true); header.setUint32(8, result.byteLength, true);
  header.setUint32(12, paddedLength, true); header.setUint32(16, 0x4e4f534a, true);
  new Uint8Array(result, 20, paddedLength).fill(0x20);
  new Uint8Array(result, 20, json.length).set(json);
  header.setUint32(20 + paddedLength, binary.length, true); header.setUint32(24 + paddedLength, 0x004e4942, true);
  new Uint8Array(result, 28 + paddedLength).set(binary);
  return result;
}
