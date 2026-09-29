/**
 * Đọc geometry PLY bằng parser Three.js; giữ parser ASCII nghiêm ngặt cho fixture.
 * Đây là geometry/point-cloud loader, không thay thế Gaussian renderer.
 */

import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";

export interface PlyCloud {
  /** Toạ độ phẳng [x0,y0,z0,x1,y1,z1,...] để đưa thẳng vào BufferAttribute. */
  positions: Float32Array;
  vertexCount: number;
  /** Comment trong header, giữ nguyên để UI hiện được nguồn gốc fixture. */
  comments: string[];
  indices?: Uint32Array;
}

export class PlyFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlyFormatError";
  }
}

const HEADER_END = "end_header";

interface Header {
  format: string;
  vertexCount: number;
  vertexProperties: number;
  properties: string[];
  comments: string[];
  bodyStart: number;
}

function parseHeader(text: string): Header {
  const lines = text.split(/\r?\n/);
  if (lines[0]?.trim() !== "ply") throw new PlyFormatError("PLY thiếu magic header");
  let format = "";
  let vertexCount = 0;
  let vertexProperties = 0;
  const properties: string[] = [];
  const comments: string[] = [];
  let inVertexElement = false;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]!.trim();
    if (line === HEADER_END) {
      return { format, vertexCount, vertexProperties, properties, comments, bodyStart: index + 1 };
    }
    if (line.startsWith("comment")) {
      comments.push(line.slice("comment".length).trim());
      continue;
    }
    if (line.startsWith("format")) {
      format = line.slice("format".length).trim();
      continue;
    }
    if (line.startsWith("element")) {
      const [, name, count] = line.split(/\s+/);
      inVertexElement = name === "vertex";
      if (inVertexElement) {
        if (!/^\d+$/.test(count ?? "")) throw new PlyFormatError("PLY vertex count không hợp lệ");
        vertexCount = Number(count);
      }
      continue;
    }
    if (line.startsWith("property") && inVertexElement) {
      if (line.split(/\s+/)[1] === "list") throw new PlyFormatError("Chưa hỗ trợ list property trong vertex");
      vertexProperties += 1;
      properties.push(line.split(/\s+/).at(-1)!);
    }
  }
  throw new PlyFormatError("PLY thiếu dòng end_header");
}

/** Parse ASCII PLY; ném `PlyFormatError` với mọi định dạng không hỗ trợ. */
export function parseAsciiPly(text: string): PlyCloud {
  const header = parseHeader(text);
  if (header.format !== "ascii 1.0") {
    throw new PlyFormatError(`chỉ hỗ trợ PLY ascii 1.0, nhận được: ${header.format || "(thiếu format)"}`);
  }
  if (!["x", "y", "z"].every((field) => header.properties.includes(field))) {
    throw new PlyFormatError("PLY thiếu property toạ độ");
  }
  if (!Number.isSafeInteger(header.vertexCount) || header.vertexCount <= 0 || header.vertexCount > 20_000_000) {
    throw new PlyFormatError("PLY vertex count không hợp lệ hoặc vượt giới hạn viewer");
  }

  const body = text.split(/\r?\n/).slice(header.bodyStart);
  const positions = new Float32Array(header.vertexCount * 3);
  let written = 0;

  for (const rawLine of body) {
    const line = rawLine.trim();
    if (line === "" || written >= header.vertexCount) {
      continue;
    }
    const parts = line.split(/\s+/);
    if (parts.length < header.vertexProperties) {
      throw new PlyFormatError(`dòng vertex không đủ ${header.vertexProperties} property: "${line}"`);
    }
    for (let axis = 0; axis < 3; axis += 1) {
      const value = Number(parts[header.properties.indexOf(["x", "y", "z"][axis]!)]!);
      if (!Number.isFinite(value) || Math.abs(value) > 3.402823466e38) {
        throw new PlyFormatError(`toạ độ không phải số: "${parts[axis]}"`);
      }
      positions[written * 3 + axis] = value;
    }
    written += 1;
  }

  if (written !== header.vertexCount) {
    throw new PlyFormatError(`PLY khai ${header.vertexCount} vertex nhưng chỉ đọc được ${written}`);
  }
  return { positions, vertexCount: header.vertexCount, comments: header.comments };
}

/** Reuse parser Three.js cho ASCII/binary PLY và face indices, không đoán xyz theo thứ tự cột. */
export function parsePly(buffer: ArrayBuffer): PlyCloud {
  const prefix = new TextDecoder().decode(buffer.slice(0, Math.min(buffer.byteLength, 65536)));
  const header = parseHeader(prefix);
  if (!["ascii 1.0", "binary_little_endian 1.0", "binary_big_endian 1.0"].includes(header.format)) {
    throw new PlyFormatError("PLY format không được hỗ trợ");
  }
  if (!Number.isSafeInteger(header.vertexCount) || header.vertexCount <= 0 || header.vertexCount > 20_000_000 ||
      !["x", "y", "z"].every((field) => header.properties.includes(field))) {
    throw new PlyFormatError("PLY header không hợp lệ");
  }
  if (header.format === "ascii 1.0") parseAsciiPly(new TextDecoder().decode(buffer));
  const geometry = new PLYLoader().parse(buffer);
  try {
    const positions = Float32Array.from(geometry.getAttribute("position").array);
    if (positions.length !== header.vertexCount * 3 || !positions.every(Number.isFinite)) {
      throw new PlyFormatError("PLY payload thiếu hoặc có toạ độ không hữu hạn");
    }
    const indices = geometry.index ? Uint32Array.from(geometry.index.array) : undefined;
    if (indices && (indices.length % 3 !== 0 || !indices.every((index) => index < header.vertexCount))) {
      throw new PlyFormatError("PLY face index nằm ngoài vertex inventory");
    }
    return { positions, vertexCount: header.vertexCount, comments: header.comments, indices };
  } finally { geometry.dispose(); }
}
