/**
 * Đọc PLY ASCII thành mảng điểm.
 *
 * Chỉ hỗ trợ `format ascii 1.0`. PLY binary cố tình **không** được parse ở đây:
 * đoán sai layout binary sẽ cho ra hình dạng trông hợp lệ nhưng sai, đúng kiểu
 * lỗi mà PRODUCT-06 §11 cấm báo cáo thành bằng chứng render.
 */

export interface PlyCloud {
  /** Toạ độ phẳng [x0,y0,z0,x1,y1,z1,...] để đưa thẳng vào BufferAttribute. */
  positions: Float32Array;
  vertexCount: number;
  /** Comment trong header, giữ nguyên để UI hiện được nguồn gốc fixture. */
  comments: string[];
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
  comments: string[];
  bodyStart: number;
}

function parseHeader(text: string): Header {
  const lines = text.split(/\r?\n/);
  let format = "";
  let vertexCount = 0;
  let vertexProperties = 0;
  const comments: string[] = [];
  let inVertexElement = false;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]!.trim();
    if (line === HEADER_END) {
      return { format, vertexCount, vertexProperties, comments, bodyStart: index + 1 };
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
        vertexCount = Number.parseInt(count ?? "0", 10);
      }
      continue;
    }
    if (line.startsWith("property") && inVertexElement) {
      vertexProperties += 1;
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
  if (header.vertexProperties < 3) {
    throw new PlyFormatError("PLY thiếu property toạ độ");
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
      const value = Number.parseFloat(parts[axis]!);
      if (Number.isNaN(value)) {
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
