/**
 * Renderer của viewer 3DGS (T-065). Mặc định `webgl` như trước; đặt `NEXT_PUBLIC_VIEWER_RENDERER=auto` để dùng WebGPU khi trình
 * duyệt hỗ trợ (thử nghiệm). Giá trị khác coi như `webgl`.
 */
export function viewerRenderer(
  setting: string | undefined = process.env.NEXT_PUBLIC_VIEWER_RENDERER,
  hasWebGpu: boolean = typeof navigator !== "undefined" && "gpu" in navigator,
): "webgpu" | "webgl" {
  return setting === "auto" && hasWebGpu ? "webgpu" : "webgl";
}
