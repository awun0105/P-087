"use client";

import { Info, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/studio/primitives";
import { INITIAL_RUNTIME, PlayCanvasScene, usePlayCanvasCapability } from "@/features/viewer/PlayCanvasScene";

/**
 * Entry của SuperSplat editor đã build (`npm run build:editor` → public/editor).
 * Trỏ thẳng index.html: Next bỏ dấu `/` cuối nên `/editor/` sẽ thành `/editor` (404).
 */
const EDITOR_PATH = "/editor/index.html";

type Mode = "checking" | "editor" | "viewer";

interface GpuNavigator {
  gpu?: { requestAdapter: () => Promise<unknown | null> };
}

/** SuperSplat 3.4.2 chỉ chạy trên WebGPU (vendor `src/index.ts`); cần adapter thật, không chỉ `navigator.gpu`. */
async function hasWebGpuAdapter(): Promise<boolean> {
  const gpu = (navigator as Navigator & GpuNavigator).gpu;
  if (!gpu) return false;
  try {
    return (await gpu.requestAdapter()) !== null;
  } catch {
    return false;
  }
}

/**
 * Nhúng SuperSplat editor (vendor, MIT) cùng origin và nạp đúng file 3DGS qua
 * `?load=`. Trình duyệt không có WebGPU → chế độ chỉ xem bằng viewer PlayCanvas
 * WebGL2 sẵn có (baseline P0), kèm lý do rõ ràng thay vì màn hình lỗi.
 */
export function EditorFrame({
  contentUrl,
  filename,
  homeHref,
  title,
}: {
  contentUrl: string;
  filename: string;
  homeHref: string;
  title: string;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("checking");
  const [loaded, setLoaded] = useState(false);
  const src = `${EDITOR_PATH}?${new URLSearchParams({ load: contentUrl, filename }).toString()}`;

  useEffect(() => {
    let alive = true;
    void hasWebGpuAdapter().then((ok) => {
      if (alive) setMode(ok ? "editor" : "viewer");
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (typeof event.data === "object" && event.data?.type === "supersplat:navigate-home") {
        router.push(homeHref);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [router, homeHref]);

  if (mode === "viewer") {
    return <WebGlViewer contentUrl={contentUrl} filename={filename} onTryEditor={() => setMode("editor")} />;
  }

  return (
    <div className="relative size-full bg-viewport">
      {(mode === "checking" || !loaded) && (
        <div className="absolute inset-0 z-10 grid place-items-center text-ink/80" role="status">
          <div className="flex flex-col items-center gap-3 text-sm">
            <Loader2 className="size-6 animate-spin text-ember motion-reduce:animate-none" aria-hidden />
            {mode === "checking" ? "Đang kiểm tra WebGPU…" : "Đang mở editor 3D…"}
          </div>
        </div>
      )}
      {mode === "editor" && (
        <iframe
          key={src}
          src={src}
          title={title}
          onLoad={() => setLoaded(true)}
          className="size-full border-0"
          allow="fullscreen; clipboard-write; xr-spatial-tracking"
        />
      )}
    </div>
  );
}

/** Viewer WebGL2 (PlayCanvas + supersplat-viewer): xem, xoay, zoom — không có công cụ chỉnh sửa. */
function WebGlViewer({ contentUrl, filename, onTryEditor }: { contentUrl: string; filename: string; onTryEditor: () => void }) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const failed = capability === "failed" || capability === "unavailable";
  return (
    <div className="relative size-full bg-viewport">
      <div className="absolute top-3 left-1/2 z-10 flex w-[min(92%,44rem)] -translate-x-1/2 items-start gap-3 rounded-xl border border-ochre/40 bg-paper-raised/95 px-4 py-3 text-sm text-ink shadow-md">
        <Info className="mt-0.5 size-4 shrink-0 text-ochre" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium">Chế độ chỉ xem (WebGL2)</p>
          <p className="text-ink-muted">
            Trình duyệt chưa có WebGPU nên editor chỉnh sửa không chạy được. Dùng Chrome/Edge bản mới có WebGPU (kiểm tra
            tại chrome://gpu) để chọn, xóa và export.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onTryEditor}>
          Thử mở editor
        </Button>
      </div>
      {failed ? (
        <div className="grid size-full place-items-center p-6 text-center text-sm text-ink/80" role="alert">
          Không render được 3DGS: trình duyệt cần WebGL2 hoặc WebGPU và đủ bộ nhớ GPU.
        </div>
      ) : (
        <>
          {!runtime.loaded && (
            <p className="absolute right-4 bottom-4 z-10 rounded-lg bg-viewport/80 px-3 py-1.5 text-xs text-ink/80" role="status">
              Đang nạp {Math.round(runtime.progress)}%
            </p>
          )}
          <PlayCanvasScene
            contentUrl={contentUrl}
            contentFilename={filename}
            renderer="webgl"
            showControls
            mode="VISUAL"
            capability={capability}
            onFailed={fail}
            onRuntime={setRuntime}
          />
        </>
      )}
    </div>
  );
}
