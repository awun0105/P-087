/**
 * Đọc lưới tam giác thô từ GLB (toạ độ đỉnh + chỉ số), không áp transform của node — đúng cách viewer đọc lưới va
 * chạm. Dùng cho lớp vật lý phía trình duyệt; chỉ nhận layout của lưới va chạm và collider mà backend sinh ra.
 */

const MAGIC = 0x46546c67;
const JSON_CHUNK = 0x4e4f534a;
const BIN_CHUNK = 0x004e4942;
const FLOAT = 5126;
const INDEX_ARRAYS = { 5121: Uint8Array, 5123: Uint16Array, 5125: Uint32Array } as const;

interface Accessor { bufferView: number; byteOffset?: number; componentType: number; count: number; type: string }
interface BufferView { byteOffset?: number; byteStride?: number }
interface Primitive { attributes: { POSITION?: number }; indices?: number; mode?: number }
interface Document { accessors: Accessor[]; bufferViews: BufferView[]; meshes?: { primitives: Primitive[] }[] }

export interface TriangleMesh {
  /** xyz liên tiếp. */
  positions: Float32Array;
  /** Ba chỉ số một tam giác, trỏ vào `positions`. */
  indices: Uint32Array;
}

export function parseGlbMesh(buffer: ArrayBuffer): TriangleMesh {
  const view = new DataView(buffer);
  if (buffer.byteLength < 20 || view.getUint32(0, true) !== MAGIC || view.getUint32(4, true) !== 2) throw new Error("Không phải GLB 2.0");
  const jsonLength = view.getUint32(12, true);
  if (view.getUint32(16, true) !== JSON_CHUNK) throw new Error("GLB thiếu chunk JSON");
  const document = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, jsonLength))) as Document;
  const binHeader = 20 + jsonLength;
  if (binHeader + 8 > buffer.byteLength || view.getUint32(binHeader + 4, true) !== BIN_CHUNK) throw new Error("GLB thiếu chunk BIN");
  const binStart = binHeader + 8;
  const positions: number[] = [];
  const indices: number[] = [];
  for (const mesh of document.meshes ?? []) {
    for (const primitive of mesh.primitives) {
      const position = primitive.attributes.POSITION;
      if (position === undefined || (primitive.mode ?? 4) !== 4) continue;
      const accessor = document.accessors[position];
      if (accessor.componentType !== FLOAT || accessor.type !== "VEC3") throw new Error("POSITION không phải float32 VEC3");
      const bufferView = document.bufferViews[accessor.bufferView];
      const stride = bufferView.byteStride ?? 12;
      const start = binStart + (bufferView.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
      const base = positions.length / 3;
      for (let i = 0; i < accessor.count; i += 1) {
        const offset = start + i * stride;
        positions.push(view.getFloat32(offset, true), view.getFloat32(offset + 4, true), view.getFloat32(offset + 8, true));
      }
      if (primitive.indices === undefined) {
        for (let i = 0; i + 2 < accessor.count; i += 3) indices.push(base + i, base + i + 1, base + i + 2);
        continue;
      }
      const indexAccessor = document.accessors[primitive.indices];
      const Kind = INDEX_ARRAYS[indexAccessor.componentType as keyof typeof INDEX_ARRAYS];
      if (!Kind) throw new Error("Kiểu chỉ số không hỗ trợ");
      const indexView = document.bufferViews[indexAccessor.bufferView];
      const indexStart = binStart + (indexView.byteOffset ?? 0) + (indexAccessor.byteOffset ?? 0);
      const source = new Kind(buffer.slice(indexStart, indexStart + indexAccessor.count * Kind.BYTES_PER_ELEMENT));
      for (const index of source) indices.push(base + index);
    }
  }
  if (!indices.length) throw new Error("GLB không có tam giác");
  return { positions: new Float32Array(positions), indices: new Uint32Array(indices) };
}
