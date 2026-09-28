"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  PlayCanvasScene, detectPlayCanvasCapability, usePlayCanvasCapability, INITIAL_RUNTIME,
  type PlayCanvasRuntime,
} from "@/features/viewer/PlayCanvasScene";
import { validateLocalSplat } from "@/features/viewer/local-splat";
import { SplatInspectionToolbar } from "./SplatInspectionToolbar";
import type { SplatInspection } from "./splat-inspection";
import { EMPTY_INSPECTION } from "./inspection-history";
import { RendererPreference } from "./RendererPreference";

/** File chỉ sống trong browser; không tạo job, SceneIR hay metric confirmation giả. */
export function LocalSplatViewer() {
  const [session, setSession] = useState<{ file: File; id: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const selection = useRef(0);
  useEffect(() => () => { selection.current += 1; }, []);

  async function selectFile(candidate: File | undefined): Promise<void> {
    if (!candidate) return;
    const generation = ++selection.current;
    setBusy(true);
    setError(null);
    setSession(null);
    try {
      await validateLocalSplat(candidate);
      if (selection.current === generation) setSession({ file: candidate, id: generation });
    } catch (cause: unknown) {
      if (selection.current === generation) setError(cause instanceof Error ? cause.message : "Không đọc được file.");
    } finally {
      if (selection.current === generation) setBusy(false);
    }
  }

  return (
    <section className="space-y-4">
      <p className="text-sm text-slate-400">
        Preview cục bộ, không upload file lên backend. Chưa xác nhận đơn vị mét,
        hệ tọa độ hay collision; không dùng preview này làm kết quả nghiệm thu EX-REC.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <label className="rounded-lg border border-slate-700 p-3 text-sm">
          Chọn file Gaussian .ply / .sog
          <input className="ml-3 max-w-full" aria-label="Chọn file 3DGS" type="file" accept=".ply,.sog"
            onChange={(event) => { void selectFile(event.target.files?.[0]); event.target.value = ""; }} />
        </label>
        {session && <Button variant="secondary" onClick={() => { selection.current += 1; setSession(null); }}>Đóng file</Button>}
      </div>
      {busy && <p role="status">Đang kiểm tra header…</p>}
      {error && <p role="alert" className="text-rose-400">{error}</p>}
      {session ? <LocalSession key={session.id} file={session.file} /> :
        <p className="rounded-xl border border-dashed border-slate-700 p-12 text-center text-slate-400">
          Chọn một file để bắt đầu. File lớn có thể vượt RAM/VRAM của trình duyệt.
        </p>}
    </section>
  );
}

/** Remount khi đổi file để không giữ lỗi, camera hoặc GPU allocation của file cũ. */
function LocalSession({ file }: { file: File }) {
  const [renderer, setRenderer] = useState<"webgpu" | "webgl">("webgpu");
  const [capability, setCapability] = usePlayCanvasCapability();
  const [runtime, setRuntime] = useState<PlayCanvasRuntime>(INITIAL_RUNTIME);
  const [inspection, setInspection] = useState(EMPTY_INSPECTION);
  const [controller, setController] = useState<SplatInspection | null>(null);
  const fail = useCallback(() => setCapability("failed"), [setCapability]);

  return <div className="space-y-3">
    <p className="break-all text-sm">{file.name} · {(file.size / 1048576).toFixed(1)} MiB</p>
    <p className="text-sm text-slate-400">Dùng chuột để orbit/rotate, pan và zoom; mở Help trong viewer để xem thao tác và phím tắt.</p>
    <RendererPreference value={renderer} actual={runtime.graphicsBackend} onChange={(value) => {
      setRenderer(value); setCapability(detectPlayCanvasCapability()); setRuntime(INITIAL_RUNTIME); setInspection(EMPTY_INSPECTION);
    }} />
    <SplatInspectionToolbar controller={controller} state={inspection} loaded={runtime.loaded} />
    {capability === "failed" ? <p role="alert" className="text-rose-400">Không nạp được 3DGS. File có thể hỏng, không tương thích hoặc vượt tài nguyên GPU. Hãy thử file khác.</p> :
      capability === "unavailable" ? <p role="alert">Trình duyệt không có WebGPU/WebGL2. Kiểm tra hardware acceleration/GPU.</p> :
        <>
          <p role="status" className="text-xs text-slate-400">{runtime.loaded ? "Đã render frame đầu" : `Đang nạp: ${Math.round(runtime.progress)}%`}</p>
          <div className="relative h-[65vh] min-h-80 overflow-hidden rounded-xl border border-slate-700">
            <PlayCanvasScene contentUrl={null} contentFile={file} renderer={renderer} showControls mode="VISUAL"
              capability={capability} onFailed={fail} onRuntime={setRuntime} enableInspection
              onInspectionReady={setController} onInspectionState={setInspection} />
          </div>
        </>}
  </div>;
}
