"use client";

import { errorMessage } from "@/lib/ui-error";

import { Loader2 } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { Notice } from "@/components/studio/primitives";
import { jobArtifactContentUrl, jobFrameThumbnailUrl } from "@/lib/api/endpoints";
import { getStageViews } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { StageView } from "@/lib/contracts/studio";

/** T-065: three/r3f/PlayCanvas chỉ tải khi lớp đang xem cần 3D; Frames và Cameras không kéo chúng. */
const Stage3DLayer = dynamic(() => import("@/features/studio/StageViewer3D").then((m) => m.Stage3DLayer), {
  ssr: false,
  loading: () => (
    <p className="flex items-center gap-2 p-6 text-sm text-ink-muted" role="status">
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tải khung xem 3D…
    </p>
  ),
});

/**
 * Kết quả từng bước của pipeline (ADR 0005): frame, camera, 3DGS, collision mesh.
 * Danh sách do backend trả; mỗi lúc chỉ nạp một lớp và giải phóng lớp cũ khi đổi.
 */
export function StageViewer({ jobId, stageId, fallbackStageId }: { jobId: string; stageId?: string; fallbackStageId?: string }) {
  const [views, setViews] = useState<StageView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getStageViews(jobId, controller.signal).then(
      (result) => {
        if (controller.signal.aborted) return;
        setViews(result);
        setSelected(Math.max(0, result.length - 1));
      },
      (cause: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(cause, "Không tải được kết quả"));
      },
    );
    return () => controller.abort();
  }, [jobId]);

  if (error) return <Notice tone="rust">{error}</Notice>;
  if (!views) {
    return (
      <p className="flex items-center gap-2 p-6 text-sm text-ink-muted" role="status">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tải kết quả các bước…
      </p>
    );
  }
  const exact = stageId ? views.filter((view) => view.stage_id === stageId) : views;
  const fallback = exact.length === 0 && fallbackStageId ? views.filter((view) => view.stage_id === fallbackStageId) : [];
  const available = exact.length ? exact : fallback;
  if (!available.length) return <Notice>{stageId ? "Giai đoạn đã xong nhưng API chưa cung cấp lớp xem cho giai đoạn này. Xem metadata và artifact đã publish trong Thông tin đầu ra." : "Chưa có bước nào xong để xem."}</Notice>;
  const selectedIndex = Math.min(selected, available.length - 1);
  const view = available[selectedIndex];
  return (
    <div className="flex size-full flex-col">
      {fallback.length > 0 && <Notice tone="ochre" className="shrink-0 rounded-none">Bản xác nhận tỉ lệ đã có, nhưng API chưa cung cấp 3DGS hệ mét (bản dẫn xuất xuất hiện khi worker hoàn tất hình học). Đang xem lại Gaussian gốc, đơn vị SfM; số đo đã xác nhận xem trong “Xem số đo & so sánh”.</Notice>}
      {available.length > 1 && <div className="flex flex-wrap gap-1 border-b border-line bg-paper-raised px-3 py-2" role="tablist" aria-label="Kết quả từng bước">
        {available.map((item, index) => (
          <button
            key={`${item.stage_id}-${item.kind}`}
            type="button"
            role="tab"
            aria-selected={index === selectedIndex}
            onClick={() => setSelected(index)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm transition-colors",
              index === selectedIndex ? "bg-ember-soft font-medium text-ember-strong" : "text-ink-muted hover:bg-paper-sunken",
            )}
          >
            {item.title}
          </button>
        ))}
      </div>}
      <div className="relative min-h-0 flex-1 bg-viewport" role="tabpanel">
        {/* `key` buộc unmount lớp cũ để giải phóng GPU/listener trước khi nạp lớp mới. */}
        <StageLayer key={`${view.stage_id}-${view.kind}`} jobId={jobId} view={view} views={views} />
      </div>
    </div>
  );
}

function StageLayer({ jobId, view, views }: { jobId: string; view: StageView; views: StageView[] }) {
  if (view.kind === "frames") return <FramesLayer jobId={jobId} view={view} />;
  if (view.kind === "cameras") return <CamerasLayer view={view} />;
  return <Stage3DLayer jobId={jobId} view={view} views={views} />;
}

function FramesLayer({ jobId, view }: { jobId: string; view: StageView }) {
  // T-066: lưới dùng ảnh thu nhỏ (vài chục KB); ảnh gốc (tới 8 MB) chỉ tải khi bấm vào một ảnh.
  const [open, setOpen] = useState<StageView["refs"][number] | null>(null);
  const name = (ref: StageView["refs"][number]) => ref.artifact_uri.split("/").pop() ?? "frame";
  return (
    <div className="relative size-full">
      <div className="grid size-full auto-rows-min grid-cols-2 gap-2 overflow-y-auto bg-paper p-3 sm:grid-cols-4 lg:grid-cols-6">
        {view.refs.map((ref) => (
          <button key={ref.artifact_uri} type="button" aria-label={`Xem ảnh gốc ${name(ref)}`} onClick={() => setOpen(ref)} className="block rounded-md focus-visible:outline-2 focus-visible:outline-ember">
            {/* eslint-disable-next-line @next/next/no-img-element -- ảnh artifact có checksum, không qua next/image optimizer */}
            <img
              src={jobFrameThumbnailUrl(jobId, ref, 320)}
              srcSet={`${jobFrameThumbnailUrl(jobId, ref, 160)} 160w, ${jobFrameThumbnailUrl(jobId, ref, 320)} 320w, ${jobFrameThumbnailUrl(jobId, ref, 640)} 640w`}
              sizes="(min-width: 1024px) 16vw, (min-width: 640px) 25vw, 50vw"
              alt={name(ref)}
              loading="lazy"
              decoding="async"
              className="aspect-video w-full rounded-md border border-line object-cover"
            />
          </button>
        ))}
      </div>
      {open && (
        <div role="dialog" aria-label={`Ảnh gốc ${name(open)}`} className="absolute inset-0 z-30 flex flex-col bg-viewport-deep/95 p-3">
          <div className="mb-2 flex items-center justify-between text-sm text-on-dark">
            <span className="truncate">{name(open)}</span>
            <button type="button" onClick={() => setOpen(null)} className="rounded px-2 py-1 hover:bg-on-dark/10">Đóng ảnh gốc</button>
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element -- ảnh gốc có checksum */}
          <img src={jobArtifactContentUrl(jobId, open)} alt={`Ảnh gốc ${name(open)}`} className="min-h-0 flex-1 object-contain" />
        </div>
      )}
    </div>
  );
}

/** Nhìn từ trên xuống: hai trục trải rộng nhất (SfM không biết trục nào là "lên"). */
export function topDownAxes(view: StageView): [number, number] {
  if (view.unit === "meter") return [0, 1];
  const spread = [0, 1, 2].map((axis) => {
    const values = view.cameras.map((camera) => camera.center[axis]);
    return Math.max(...values) - Math.min(...values);
  });
  const order = [0, 1, 2].sort((a, b) => spread[b] - spread[a]);
  return [order[0], order[1]].sort((a, b) => a - b) as [number, number];
}

function CamerasLayer({ view }: { view: StageView }) {
  const [u, v] = topDownAxes(view);
  const points = view.cameras.map((camera) => [camera.center[u], camera.center[v]] as const);
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const size = Math.max(maxX - minX, maxY - minY) || 1;
  const pad = size * 0.08;
  const box = `${minX - pad} ${-(maxY + pad)} ${size + 2 * pad} ${size + 2 * pad}`;
  const path = points.map(([x, y], index) => `${index ? "L" : "M"}${x} ${-y}`).join(" ");
  return (
    <div className="grid size-full place-items-center bg-paper p-4">
      <svg viewBox={box} className="h-full max-h-[70vh] w-full" role="img" aria-label="Quỹ đạo camera nhìn từ trên xuống">
        <path d={path} fill="none" stroke="currentColor" strokeWidth={size / 300} className="text-ink-subtle" />
        {points.map(([x, y], index) => (
          <circle key={index} cx={x} cy={-y} r={size / (index === 0 ? 80 : 160)} className={index === 0 ? "fill-ember" : "fill-ink-muted"} />
        ))}
      </svg>
      <p className="text-xs text-ink-muted">
        {view.cameras.length} camera · chấm cam là frame đầu{view.unit === "meter" ? " · khung ngang theo mét" : ""}
      </p>
    </div>
  );
}
