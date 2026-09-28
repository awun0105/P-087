"use client";

import { useCallback, useState } from "react";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import type { ReconstructionPreview } from "@/lib/contracts/preview";
import { PlayCanvasScene, INITIAL_RUNTIME, detectPlayCanvasCapability, type PlayCanvasCapability } from "./PlayCanvasScene";

/** Preview native SfM, không áp rotation canonical Z-up của SceneIR vào đây. */
export function ReconstructionPreviewPanel({ preview }: { preview: ReconstructionPreview }) {
  const [capability, setCapability] = useState<PlayCanvasCapability>(detectPlayCanvasCapability);
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const fail = useCallback(() => setCapability("failed"), []);
  return <section className="space-y-3">
    <p className="rounded-lg border border-amber-700 bg-amber-950/20 p-3 text-sm text-amber-200">
      3DGS preview · metric chưa xác nhận · đơn vị SfM tùy ý. Chưa có SceneIR/collision;
      đây không phải scene sẵn sàng cho simulation.
    </p>
    <p className="text-xs text-slate-400">Brush {preview.producer_version} · attempt {preview.attempt_id}</p>
    {capability === "failed" || capability === "unavailable" ?
      <p role="alert" className="text-rose-400">Không nạp được 3DGS. Kiểm tra artifact, tài nguyên GPU và WebGL2 của trình duyệt.</p> : <>
        <p role="status" className="text-xs text-slate-400">{runtime.loaded ? "Đã render frame đầu" : `Đang nạp ${Math.round(runtime.progress)}%`}</p>
        <div className="relative h-[65vh] min-h-80 overflow-hidden rounded-xl border border-slate-700">
          <PlayCanvasScene contentUrl={jobArtifactContentUrl(preview.job_id, preview.delivery_ref)}
            contentFilename="scene.sog" showControls mode="VISUAL" capability={capability} onFailed={fail} onRuntime={setRuntime} />
        </div>
      </>}
  </section>;
}
