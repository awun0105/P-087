"use client";
import { useCallback, useState } from "react";
import { PlayCanvasScene, usePlayCanvasCapability, INITIAL_RUNTIME } from "@/features/viewer/PlayCanvasScene";
import type { Preview } from "@/features/studio/scene/state";

/** Bản xem SfM trung tính; chỉnh Gaussian chỉ mở khi người dùng chọn chế độ đó. */
export function PreviewScene({ preview }: { preview: Preview }) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  return <div className="relative size-full bg-viewport">
    {capability === "failed" || capability === "unavailable" ? <p role="alert" className="grid size-full place-items-center p-6 text-sm text-paper">Không mở được 3DGS. Trình duyệt cần WebGL2/WebGPU và đủ bộ nhớ GPU.</p> : <>
      {!runtime.loaded && <p role="status" className="absolute top-3 left-3 z-10 rounded border border-line-dark bg-viewport-deep/85 p-2 text-sm text-paper">Đang tải bản xem 3DGS…</p>}
      <PlayCanvasScene contentUrl={preview.url} contentFilename={preview.filename} renderer="webgl" mode="VISUAL" showControls capability={capability} onFailed={fail} onRuntime={setRuntime} />
    </>}
  </div>;
}
