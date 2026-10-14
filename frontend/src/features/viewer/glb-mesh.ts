/**
 * Đọc geometry đã bake từ GLB physics; không tự suy frame từ quy ước glTF.
 * Chỉ nhận node identity và mỗi mesh xuất hiện một lần trong scene. Transform chưa bake phải báo lỗi,
 * vì walk viewer cũng đọc đỉnh thô và bỏ qua node transforms.
 */

const MAGIC = 0x46546c67;
const JSON_CHUNK = 0x4e4f534a;
const BIN_CHUNK = 0x004e4942;
const FLOAT = 5126;
const INDEX_ARRAYS = { 5121: Uint8Array, 5123: Uint16Array, 5125: Uint32Array } as const;

interface Accessor { bufferView: number; byteOffset?: number; componentType: number; count: number; type: string; sparse?: object; normalized?: boolean }
interface BufferView { buffer: number; byteLength: number; byteOffset?: number; byteStride?: number }
interface Primitive { attributes: { POSITION?: number }; indices?: number; mode?: number; targets?: object[]; extensions?: object }
interface MeshNode { mesh?: number; children?: number[]; matrix?: number[]; translation?: number[]; rotation?: number[]; scale?: number[]; skin?: number }
interface Document {
  buffers: { byteLength: number; uri?: string }[];
  accessors: Accessor[];
  bufferViews: BufferView[];
  meshes?: { primitives: Primitive[]; weights?: number[] }[];
  nodes?: MeshNode[];
  scenes?: { nodes: number[] }[];
  scene?: number;
  animations?: object[];
  extensionsUsed?: string[];
}

/** Lỗi geometry/layout không được đổi âm thầm thành box fallback ở loader. */
export class GlbMeshError extends Error {}

function requireLayout(condition: boolean, message: string): asserts condition {
  if (!condition) throw new GlbMeshError(`GLB: ${message}`);
}

function validateNodes(document: Document): void {
  requireLayout(!document.animations?.length && !document.extensionsUsed?.length, "animation/extensions chưa hỗ trợ");
  // Layout chỉ có mesh/accessors là đỉnh đã bake, không có node transform để áp dụng.
  if (document.nodes === undefined) {
    requireLayout(document.scenes === undefined && document.scene === undefined, "scene thiếu nodes");
    return;
  }
  requireLayout(document.scenes?.length === 1 && (document.scene ?? 0) === 0, "chỉ hỗ trợ một scene có nodes");
  const visited = new Set<number>();
  const meshes = new Set<number>();
  const identity = (values: number[] | undefined, expected: number[]) =>
    values === undefined || (values.length === expected.length && values.every((value, index) => value === expected[index]));
  const visit = (index: number) => {
    const node = document.nodes![index];
    requireLayout(Number.isInteger(index) && !!node && !visited.has(index), "node không hợp lệ, có cycle hoặc instance lặp");
    visited.add(index);
    requireLayout(node.skin === undefined, "node skin chưa hỗ trợ");
    requireLayout(node.matrix === undefined || (node.translation === undefined && node.rotation === undefined && node.scale === undefined), "node chứa cả matrix và TRS");
    requireLayout(
      identity(node.matrix, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) &&
      identity(node.translation, [0, 0, 0]) && identity(node.scale, [1, 1, 1]) &&
      (identity(node.rotation, [0, 0, 0, 1]) || identity(node.rotation, [0, 0, 0, -1])),
      "node transform chưa bake; cần geometry với node identity",
    );
    if (node.mesh !== undefined) {
      requireLayout(Number.isInteger(node.mesh) && !!document.meshes?.[node.mesh] && !meshes.has(node.mesh), "mesh node không hợp lệ hoặc instance lặp");
      meshes.add(node.mesh);
    }
    for (const child of node.children ?? []) visit(child);
  };
  for (const root of document.scenes![0].nodes) visit(root);
  requireLayout(visited.size === document.nodes.length && meshes.size === document.meshes?.length, "node/mesh nằm ngoài scene đang đọc");
}

function accessorRange(document: Document, index: number, binLength: number, elementBytes: number) {
  const accessor = document.accessors[index];
  requireLayout(Number.isInteger(index) && !!accessor && accessor.sparse === undefined && !accessor.normalized, "accessor không hợp lệ hoặc sparse/normalized chưa hỗ trợ");
  const bufferView = document.bufferViews[accessor.bufferView];
  requireLayout(Number.isInteger(accessor.bufferView) && !!bufferView && bufferView.buffer === 0, "bufferView không thuộc buffer nhúng");
  const offset = bufferView.byteOffset ?? 0;
  const length = bufferView.byteLength;
  const local = accessor.byteOffset ?? 0;
  const stride = bufferView.byteStride ?? elementBytes;
  requireLayout(
    [offset, length, local, stride, accessor.count].every((value) => Number.isInteger(value) && value >= 0) &&
    stride >= elementBytes && offset + length <= binLength &&
    local + (accessor.count ? (accessor.count - 1) * stride + elementBytes : 0) <= length,
    "accessor vượt ngoài bufferView/BIN hoặc stride không hợp lệ",
  );
  return { accessor, bufferView, start: offset + local, stride };
}

export interface TriangleMesh {
  /** xyz liên tiếp. */
  partCount?: number;
  positions: Float32Array;
  /** Ba chỉ số một tam giác, trỏ vào `positions`. */
  indices: Uint32Array;
}

export function parseGlbMesh(buffer: ArrayBuffer): TriangleMesh {
  try {
    return readBakedMesh(buffer);
  } catch (error: unknown) {
    if (error instanceof GlbMeshError) throw error;
    throw new GlbMeshError(`GLB không hợp lệ: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function readBakedMesh(buffer: ArrayBuffer): TriangleMesh {
  const view = new DataView(buffer);
  requireLayout(buffer.byteLength >= 20 && view.getUint32(0, true) === MAGIC && view.getUint32(4, true) === 2 && view.getUint32(8, true) === buffer.byteLength, "không phải GLB 2.0 đầy đủ");
  const jsonLength = view.getUint32(12, true);
  requireLayout(view.getUint32(16, true) === JSON_CHUNK && jsonLength % 4 === 0 && 20 + jsonLength <= buffer.byteLength, "chunk JSON không hợp lệ");
  const document = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, jsonLength))) as Document;
  const binHeader = 20 + jsonLength;
  requireLayout(binHeader + 8 <= buffer.byteLength && view.getUint32(binHeader + 4, true) === BIN_CHUNK, "thiếu chunk BIN");
  const binStart = binHeader + 8;
  const binLength = view.getUint32(binHeader, true);
  requireLayout(binStart + binLength === buffer.byteLength && binLength % 4 === 0, "chunk BIN bị cắt hoặc có chunk chưa hỗ trợ");
  requireLayout(document.buffers?.length === 1 && document.buffers[0].uri === undefined && Number.isInteger(document.buffers[0].byteLength) && document.buffers[0].byteLength > 0 && document.buffers[0].byteLength <= binLength && binLength - document.buffers[0].byteLength <= 3, "chỉ hỗ trợ một buffer nhúng");
  validateNodes(document);
  const positions: number[] = [];
  const indices: number[] = [];
  for (const mesh of document.meshes ?? []) {
    requireLayout(!mesh.weights?.length, "mesh morph weights chưa hỗ trợ");
    for (const primitive of mesh.primitives) {
      const position = primitive.attributes.POSITION;
      requireLayout(position !== undefined && (primitive.mode ?? 4) === 4 && !primitive.targets?.length && primitive.extensions === undefined, "primitive phải là triangle POSITION, không morph/compression");
      const { accessor, start, stride } = accessorRange(document, position, document.buffers[0].byteLength, 12);
      requireLayout(accessor.componentType === FLOAT && accessor.type === "VEC3" && accessor.count > 0 && start % 4 === 0 && stride % 4 === 0, "POSITION phải là float32 VEC3");
      const base = positions.length / 3;
      for (let i = 0; i < accessor.count; i += 1) {
        const offset = binStart + start + i * stride;
        const point = [view.getFloat32(offset, true), view.getFloat32(offset + 4, true), view.getFloat32(offset + 8, true)];
        requireLayout(point.every(Number.isFinite), "POSITION có giá trị không hữu hạn");
        positions.push(...point);
      }
      if (primitive.indices === undefined) {
        requireLayout(accessor.count % 3 === 0, "triangle không có indices cần số đỉnh chia hết cho 3");
        for (let i = 0; i + 2 < accessor.count; i += 3) indices.push(base + i, base + i + 1, base + i + 2);
        continue;
      }
      const indexAccessor = document.accessors[primitive.indices];
      const Kind = INDEX_ARRAYS[indexAccessor?.componentType as keyof typeof INDEX_ARRAYS];
      requireLayout(!!Kind, "kiểu indices chưa hỗ trợ");
      const range = accessorRange(document, primitive.indices, document.buffers[0].byteLength, Kind.BYTES_PER_ELEMENT);
      requireLayout(indexAccessor.type === "SCALAR" && indexAccessor.count % 3 === 0 && range.bufferView.byteStride === undefined && range.start % Kind.BYTES_PER_ELEMENT === 0, "indices phải là SCALAR triangles không interleaved");
      for (let i = 0; i < indexAccessor.count; i += 1) {
        const offset = binStart + range.start + i * Kind.BYTES_PER_ELEMENT;
        const index = Kind === Uint8Array ? view.getUint8(offset) : Kind === Uint16Array ? view.getUint16(offset, true) : view.getUint32(offset, true);
        requireLayout(index < accessor.count, "indices vượt ngoài POSITION");
        indices.push(base + index);
      }
    }
  }
  requireLayout(indices.length > 0, "không có tam giác");
  return { positions: new Float32Array(positions), indices: new Uint32Array(indices), partCount: (document.meshes ?? []).reduce((count, mesh) => count + mesh.primitives.length, 0) };
}
