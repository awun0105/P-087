"use client";

import { Info, Loader2, Maximize, RotateCcw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/studio/primitives";
import { INITIAL_RUNTIME, PlayCanvasScene, usePlayCanvasCapability, type ViewerControls } from "@/features/viewer/PlayCanvasScene";
import { type SourceFrame } from "@/features/viewer/source-frame";
import { useNavigationGuard } from "@/features/shell/NavigationGuard";
import { queryEditorDirty } from "@/features/studio/editor-dirty";
import { HelpDetails } from "@/components/studio/feedback";

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
  badges,
  description,
}: {
  contentUrl: string;
  filename: string;
  homeHref: string;
  title: string;
  badges?: ReactNode;
  description?: ReactNode;
}) {
  const router = useRouter();
  const { register, navigate } = useNavigationGuard();
  const iframe = useRef<HTMLIFrameElement | null>(null);
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
      if (event.origin !== window.location.origin || event.source !== iframe.current?.contentWindow) return;
      if (typeof event.data === "object" && event.data?.type === "supersplat:navigate-home") {
        void navigate(() => router.push(homeHref), homeHref);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [router, homeHref, navigate]);

  useEffect(() => {
    const frame = iframe.current?.contentWindow;
    if (mode !== "editor" || !loaded || !frame) return;
    const controller = new AbortController();
    const source = new URL(window.location.href);
    let cached: boolean | null = null;
    let active: Promise<boolean> | null = null;
    const dirty = () => active ?? (active = queryEditorDirty(frame, controller.signal).then((result) => { cached = result; return result; }).finally(() => { active = null; }));
    const refresh = () => { void dirty().catch(() => { cached = null; }); };
    refresh();
    const timer = setInterval(refresh, 1000);
    const unregister = register({
      dirty,
      warnOnUnload: () => cached !== false,
      releases: (href) => {
        const target = new URL(href, source);
        return target.pathname !== source.pathname || (source.pathname.startsWith("/scenes/") && target.searchParams.get("mode") !== source.searchParams.get("mode"));
      },
    });
    return () => { unregister(); clearInterval(timer); controller.abort(); };
  }, [loaded, mode, register]);

  if (mode === "viewer") {
    return (
      <WebGlViewer
        contentUrl={contentUrl}
        filename={filename}
        onTryEditor={() => setMode("editor")}
        badges={badges}
        description={description}
      />
    );
  }

  return (
    <div className="relative size-full bg-viewport">
      {(mode === "checking" || !loaded) && (
        <div className="absolute inset-0 z-10 grid place-items-center text-on-dark/80" role="status">
          <div className="flex flex-col items-center gap-3 text-sm">
            <Loader2 className="size-6 animate-spin text-ember motion-reduce:animate-none" aria-hidden />
            {mode === "checking" ? "Đang kiểm tra WebGPU…" : "Đang mở editor 3D…"}
          </div>
        </div>
      )}
      {mode === "editor" && (
        <iframe
          ref={iframe}
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
function WebGlViewer({
  contentUrl,
  filename,
  onTryEditor,
  badges,
  description,
}: {
  contentUrl: string;
  filename: string;
  onTryEditor: () => void;
  badges?: ReactNode;
  description?: ReactNode;
}) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const [showNotice, setShowNotice] = useState(false);
  const [viewerControls, setViewerControls] = useState<ViewerControls | null>(null);
  const sourceFrame: SourceFrame = "colmap";
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const handleApp = useCallback((_app: unknown, controls?: ViewerControls) => {
    setViewerControls(controls ?? null);
  }, []);
  const failed = capability === "failed" || capability === "unavailable";
  
  return (
    <div className="relative size-full bg-viewport">
      <div className="absolute top-3 left-1/2 z-10 flex w-[min(92%,44rem)] -translate-x-1/2 flex-col items-center">
        {showNotice ? (
          <div className="flex w-full items-start gap-3 rounded-xl border border-ochre/40 bg-paper-raised/95 px-4 py-3 text-sm text-ink shadow-md">
            <Info className="mt-0.5 size-4 shrink-0 text-ochre" aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between">
                <p className="font-bold">Chế độ chỉ xem (WebGL2)</p>
                <button type="button" onClick={() => setShowNotice(false)} className="rounded p-1 text-ink-muted hover:bg-line-dark hover:text-ink focus-visible:outline-2 focus-visible:outline-ember" aria-label="Đóng thông báo">
                  <X className="size-4" aria-hidden />
                </button>
              </div>
              {badges && <div className="mt-2 flex flex-wrap items-center gap-2">{badges}</div>}
              {description && <p className="mt-1.5 mb-2.5 text-xs text-ink-muted leading-relaxed">{description}</p>}

              <HelpDetails title="Vì sao chỉ xem?">
                <p>Bản xem scene dùng WebGL2. Chỉ editor chỉnh Gaussian mới cần WebGPU; trình duyệt hiện chưa cung cấp adapter WebGPU nên đang mở chế độ chỉ xem.</p>
                <ul className="mt-2 ml-4 list-disc space-y-1">
                  <li>Bật <b>Hardware Acceleration</b> trong cài đặt trình duyệt.</li>
                  <li>Nếu muốn chỉnh Gaussian, dùng trình duyệt hỗ trợ WebGPU và truy cập qua HTTPS hoặc localhost.</li>
                </ul>
              </HelpDetails>
            </div>
            <Button variant="ghost" size="sm" onClick={onTryEditor}>
              Mở editor
            </Button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowNotice(true)}
            className="flex items-center gap-2 rounded-full border border-ochre/40 bg-paper-raised/95 px-3 py-1.5 text-sm font-medium text-ink shadow-sm transition-colors hover:bg-paper-raised focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember"
            aria-label="Hiện thông tin chế độ chỉ xem"
          >
            <Info className="size-4 text-ochre" aria-hidden /> Chế độ chỉ xem
          </button>
        )}
      </div>
      {failed ? (
        <div className="grid size-full place-items-center p-6 text-center text-sm text-on-dark/80" role="alert">
          {capability === "unavailable"
            ? "Không render được bản xem 3DGS: trình duyệt cần WebGL2 và đủ bộ nhớ GPU."
            : "Không thể tải mô hình 3DGS (lỗi tải file hoặc dữ liệu không hợp lệ)."}
        </div>
      ) : (
        <>
          {!runtime.loaded && (
            <p className="absolute right-4 bottom-4 z-10 rounded-lg border border-line-dark bg-viewport-deep/85 px-3 py-1.5 text-xs text-on-dark/80" role="status">
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
            sourceFrame={sourceFrame}
            onApp={handleApp}
            extraControls={
              <div
                className="sse-buttonGroup flex items-center shrink-0 border border-line-dark"
                onPointerDown={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors"
                  onClick={() => viewerControls?.frameScene()}
                  disabled={!runtime.loaded}
                  title="Căn giữa vào vật thể (Toàn cảnh)"
                  aria-label="Căn giữa vào vật thể"
                >
                  <Maximize className="size-4" aria-hidden />
                </button>
                <button
                  type="button"
                  className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors"
                  onClick={() => viewerControls?.resetCamera()}
                  disabled={!runtime.loaded}
                  title="Về vị trí ban đầu"
                  aria-label="Về vị trí ban đầu"
                >
                  <RotateCcw className="size-4" aria-hidden />
                </button>
              </div>
            }
          />
        </>
      )}
    </div>
  );
}
