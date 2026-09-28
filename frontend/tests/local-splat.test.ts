import { describe, expect, it } from "vitest";
import { validateGaussianPlyHeader } from "@/features/viewer/local-splat";

const STANDARD = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3", "opacity", "f_dc_0", "f_dc_1", "f_dc_2"];
function header(properties: string[], format = "binary_little_endian"): string {
  return `ply\nformat ${format} 1.0\nelement vertex 1\n${properties.map((name) => `property float ${name}`).join("\n")}\nend_header\n`;
}

describe("Gaussian file preflight (không phải GPU render proof)", () => {
  it("nhận Gaussian PLY chuẩn và CRLF", () => {
    expect(() => validateGaussianPlyHeader(header(STANDARD))).not.toThrow();
    expect(() => validateGaussianPlyHeader(header(STANDARD).replaceAll("\n", "\r\n"))).not.toThrow();
  });
  it("nhận header compressed với packed properties", () => {
    expect(() => validateGaussianPlyHeader(header(["packed_position", "packed_rotation", "packed_scale", "packed_color"]))).not.toThrow();
  });
  it("không giả point cloud thành Gaussian", () => {
    expect(() => validateGaussianPlyHeader(header(["x", "y", "z"]))).toThrow("thiếu thuộc tính Gaussian");
  });
  it("từ chối ASCII và header bị cắt trước native load", () => {
    expect(() => validateGaussianPlyHeader(header(STANDARD, "ascii"))).toThrow("binary little-endian");
    expect(() => validateGaussianPlyHeader(header(STANDARD).replace("end_header", "truncated"))).toThrow("end_header");
  });
});
