/** Kiểm tra sơ bộ file đơn; native PlayCanvas parser vẫn kiểm tra payload đầy đủ. */
export async function validateLocalSplat(file: File): Promise<void> {
  if (!file.size) throw new Error("File rỗng.");
  const extension = file.name.toLowerCase().split(".").pop();
  if (extension !== "ply" && extension !== "sog") {
    throw new Error("Chọn Gaussian .ply hoặc .sog đóng gói. Chưa hỗ trợ .splat, .spz hay thư mục LOD.");
  }
  const bytes = await file.slice(0, 65536).arrayBuffer();
  if (extension === "sog") {
    const view = new DataView(bytes);
    if (bytes.byteLength < 4 || view.getUint32(0, true) !== 0x04034b50) {
      throw new Error("File .sog không có header bundle ZIP hợp lệ.");
    }
    return;
  }
  validateGaussianPlyHeader(new TextDecoder().decode(bytes));
}

/** Preflight thuần; không coi header hợp lệ là bằng chứng toàn bộ payload render được. */
export function validateGaussianPlyHeader(prefix: string): void {
  const end = prefix.indexOf("end_header\n") >= 0 ? prefix.indexOf("end_header\n") : prefix.indexOf("end_header\r\n");
  if (!prefix.startsWith("ply\n") && !prefix.startsWith("ply\r\n")) {
    throw new Error("File không có header PLY.");
  }
  if (end < 0) throw new Error("Header PLY thiếu end_header hoặc vượt 64 KiB.");
  const header = prefix.slice(0, end);
  if (!/^element vertex [1-9]\d*\r?$/m.test(header)) throw new Error("PLY thiếu vertex inventory khác rỗng.");
  if (!/^format binary_little_endian 1\.0\r?$/m.test(header)) {
    throw new Error("Gaussian viewer hiện yêu cầu PLY binary little-endian 1.0; ASCII PLY không được hỗ trợ ở view này.");
  }
  // PLY point cloud/mesh không phải Gaussian: phải có scale, rotation, opacity,
  // SH hoặc layout compressed của SuperSplat. Không đoán chỉ từ đuôi file.
  const properties = new Set(Array.from(header.matchAll(/^property \w+ (\w+)\r?$/gm), (match) => match[1]));
  const standard = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3", "opacity", "f_dc_0", "f_dc_1", "f_dc_2"];
  const compressed = ["packed_position", "packed_rotation", "packed_scale", "packed_color"];
  if (!standard.every((key) => properties.has(key)) && !compressed.every((key) => properties.has(key))) {
    throw new Error("PLY thiếu thuộc tính Gaussian. Point cloud/mesh PLY không thể hiển thị như 3DGS.");
  }
}
