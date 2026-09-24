/**
 * Test cho PLY reader.
 *
 * Fixture PLY của repo là ASCII 1 vertex; reader phải đọc được nó, và phải từ
 * chối mọi thứ khác thay vì đoán. Một reader đoán bừa sẽ dựng ra hình sai nhưng
 * trông hợp lệ — đúng loại lỗi PRODUCT-06 §11 cấm báo cáo thành bằng chứng.
 */

import { describe, expect, it } from "vitest";

import { parseAsciiPly, PlyFormatError } from "@/features/viewer/ply";

const SINGLE_VERTEX = `ply
format ascii 1.0
comment synthetic object geometry
element vertex 1
property float x
property float y
property float z
end_header
1 2 0
`;

const TRIANGLE = `ply
format ascii 1.0
element vertex 3
property float x
property float y
property float z
end_header
0 0 0
1 0 0
0 1 0
`;

describe("parseAsciiPly", () => {
  it("đọc được PLY một vertex đúng như fixture của repo", () => {
    const cloud = parseAsciiPly(SINGLE_VERTEX);
    expect(cloud.vertexCount).toBe(1);
    expect(Array.from(cloud.positions)).toEqual([1, 2, 0]);
  });

  it("giữ comment của header để UI hiện được nguồn gốc fixture", () => {
    expect(parseAsciiPly(SINGLE_VERTEX).comments).toEqual(["synthetic object geometry"]);
  });

  it("đọc nhiều vertex theo đúng thứ tự", () => {
    const cloud = parseAsciiPly(TRIANGLE);
    expect(cloud.vertexCount).toBe(3);
    expect(Array.from(cloud.positions)).toEqual([0, 0, 0, 1, 0, 0, 0, 1, 0]);
  });

  it("xử lý được kết thúc dòng kiểu Windows", () => {
    expect(parseAsciiPly(TRIANGLE.replace(/\n/g, "\r\n")).vertexCount).toBe(3);
  });

  it("bỏ qua property thừa sau toạ độ", () => {
    const withNormals = `ply
format ascii 1.0
element vertex 1
property float x
property float y
property float z
property float nx
property float ny
property float nz
end_header
1 2 3 0 0 1
`;
    expect(Array.from(parseAsciiPly(withNormals).positions)).toEqual([1, 2, 3]);
  });

  it("từ chối PLY binary thay vì đoán layout", () => {
    const binary = SINGLE_VERTEX.replace("format ascii 1.0", "format binary_little_endian 1.0");
    expect(() => parseAsciiPly(binary)).toThrow(PlyFormatError);
    expect(() => parseAsciiPly(binary)).toThrow(/ascii 1.0/);
  });

  it("từ chối header thiếu end_header", () => {
    expect(() => parseAsciiPly("ply\nformat ascii 1.0\nelement vertex 1\n")).toThrow(/end_header/);
  });

  it("từ chối khi số vertex đọc được ít hơn khai báo", () => {
    expect(() => parseAsciiPly(TRIANGLE.replace("0 1 0", ""))).toThrow(/chỉ đọc được 2/);
  });

  it("từ chối toạ độ không phải số", () => {
    expect(() => parseAsciiPly(SINGLE_VERTEX.replace("1 2 0", "1 abc 0"))).toThrow(/không phải số/);
  });

  it("từ chối PLY thiếu property toạ độ", () => {
    const noCoords = `ply
format ascii 1.0
element vertex 1
property float intensity
end_header
1
`;
    expect(() => parseAsciiPly(noCoords)).toThrow(/thiếu property toạ độ/);
  });
});
