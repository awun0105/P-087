"use client";

import { useCallback, useState } from "react";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import type { ReconstructionPreview } from "@/lib/contracts/preview";
import { PlayCanvasScene, INITIAL_RUNTIME, detectPlayCanvasCapability, usePlayCanvasCapability } from "./PlayCanvasScene";
import { SplatInspectionToolbar } from "./SplatInspectionToolbar";
import type { SplatInspection } from "./splat-inspection";
import { EMPTY_INSPECTION } from "./inspection-history";
import { RendererPreference } from "./RendererPreference";

/** Preview native SfM, không áp rotation canonical Z-up của SceneIR vào đây. */
export function ReconstructionPreviewPanel({ preview }: { preview: ReconstructionPreview }) {
  const [renderer, setRenderer] = useState<"webgpu" | "webgl">("webgpu");
  const [capability, setCapability] = usePlayCanvasCapability();
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const [inspection, setInspection] = useState(EMPTY_INSPECTION);
  const [controller, setController] = useState<SplatInspection | null>(null);
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  return <section className="space-y-3">
    <p className="rounded-lg border border-amber-700 bg-amber-950/20 p-3 text-sm text-amber-200">
      3DGS preview · metric chưa xác nhận · đơn vị SfM tùy ý. Chưa có SceneIR/collision;
      đây không phải scene sẵn sàng cho simulation.
    </p>
    <p className="text-xs text-slate-400">Brush {preview.producer_version} · attempt {preview.attempt_id}</p>
    <RendererPreference value={renderer} actual={runtime.graphicsBackend} onChange={(value) => {
      setRenderer(value); setCapability(detectPlayCanvasCapability()); setRuntime(INITIAL_RUNTIME); setInspection(EMPTY_INSPECTION);
    }} />
    <SplatInspectionToolbar controller={controller} state={inspection} loaded={runtime.loaded} />
    {capability === "failed" || capability === "unavailable" ?
      <p role="alert" className="text-rose-400">Không nạp được 3DGS. Kiểm tra artifact, tài nguyên GPU và WebGL2 của trình duyệt.</p> : <>
        <p role="status" className="text-xs text-slate-400">{runtime.loaded ? "Đã render frame đầu" : `Đang nạp ${Math.round(runtime.progress)}%`}</p>
        <div className="relative h-[65vh] min-h-80 overflow-hidden rounded-xl border border-slate-700">
          <PlayCanvasScene contentUrl={jobArtifactContentUrl(preview.job_id, preview.delivery_ref)} renderer={renderer}
            contentFilename="scene.sog" showControls mode="VISUAL" capability={capability} onFailed={fail} onRuntime={setRuntime}
            enableInspection onInspectionReady={setController} onInspectionState={setInspection} />
        </div>
      </>}
  </section>;
}
