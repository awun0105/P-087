"use client";

/** Backend được yêu cầu khác backend thực tế; upstream có thể fallback WebGL2. */
export function RendererPreference({ value, actual, onChange }: {
  value: "webgpu" | "webgl"; actual?: string; onChange: (renderer: "webgpu" | "webgl") => void;
}) {
  return <label className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
    Renderer
    <select className="rounded border border-slate-700 bg-slate-950 p-1" value={value}
      onChange={(event) => onChange(event.target.value === "webgl" ? "webgl" : "webgpu")}>
      <option value="webgpu">Tự động — ưu tiên WebGPU</option>
      <option value="webgl">Ép WebGL2</option>
    </select>
    <span>Đang dùng: {actual ?? "chưa khởi tạo"}. Đổi renderer sẽ reset camera/điểm đo.</span>
  </label>;
}
