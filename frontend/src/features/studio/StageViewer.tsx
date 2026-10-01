"use client";

import { errorMessage } from "@/lib/ui-error";

import { Canvas } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { Notice } from "@/components/studio/primitives";
import { requireEmbeddedGlb } from "@/features/viewer/GlbArtifact";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import { PlayCanvasScene, usePlayCanvasCapability } from "@/features/viewer/PlayCanvasScene";
import { recordingCameraPose } from "@/features/viewer/source-frame";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import { getStageViews } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { StageView } from "@/lib/contracts/studio";

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
      <div className="flex flex-wrap gap-1 border-b border-line bg-paper-raised px-3 py-2" role="tablist" aria-label="Kết quả từng bước">
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
      </div>
      <p className="border-b border-line bg-paper px-4 py-2 text-xs text-ink-muted">
        {view.note} {view.unit === "meter" ? "Đơn vị: mét." : "Đơn vị: tùy ý (SfM)."}
      </p>
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
  // Lớp hệ mét dùng chung scene: 3DGS màu + collision mesh phủ lên, cùng hệ Z-up.
  const metric = views.find((item) => item.kind === "gaussian" && item.unit === "meter");
  const mesh = views.find((item) => item.kind === "mesh");
  if (metric?.refs[0] && (view === metric || view === mesh)) {
    return (
      <MetricSceneView
        jobId={jobId}
        visual={metric.refs[0]}
        collision={mesh?.refs[0]}
        cameras={metric.cameras}
        defaultLayers={{ splat: true, collision: view === mesh, boxes: false }}
      />
    );
  }
  if (view.kind === "gaussian") {
    // 3DGS Brush ở hệ SfM của COLMAP: cùng hệ với quỹ đạo camera của bước ước lượng camera.
    const sfm = views.find((item) => item.kind === "cameras")?.cameras ?? [];
    return <GaussianLayer jobId={jobId} view={view} cameras={view.cameras.length ? view.cameras : sfm} />;
  }
  return <MeshLayer jobId={jobId} view={view} />;
}

function FramesLayer({ jobId, view }: { jobId: string; view: StageView }) {
  return (
    <div className="grid size-full auto-rows-min grid-cols-2 gap-2 overflow-y-auto bg-paper p-3 sm:grid-cols-4 lg:grid-cols-6">
      {view.refs.map((ref) => (
        // eslint-disable-next-line @next/next/no-img-element -- ảnh artifact có checksum, không qua next/image optimizer
        <img
          key={ref.artifact_uri}
          src={jobArtifactContentUrl(jobId, ref)}
          alt={ref.artifact_uri.split("/").pop() ?? "frame"}
          loading="lazy"
          className="aspect-video w-full rounded-md border border-line object-cover"
        />
      ))}
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

function GaussianLayer({ jobId, view, cameras }: { jobId: string; view: StageView; cameras: StageView["cameras"] }) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const frame = view.unit === "meter" ? "z_up" : "colmap";
  const initialCamera = useMemo(() => recordingCameraPose(frame, cameras), [frame, cameras]);
  const ref = view.refs[0];
  if (!ref) return <Notice>Bước này chưa có file 3DGS.</Notice>;
  if (capability === "failed" || capability === "unavailable") {
    return <p className="grid size-full place-items-center text-sm text-paper/80">Trình duyệt không render được 3DGS (cần WebGL2).</p>;
  }
  return (
    <PlayCanvasScene
      contentUrl={jobArtifactContentUrl(jobId, ref)}
      contentFilename={ref.artifact_uri.split("/").pop() ?? "scene.sog"}
      renderer="webgl"
      showControls
      mode="VISUAL"
      capability={capability}
      onFailed={fail}
      sourceFrame={frame}
      initialCamera={initialCamera}
    />
  );
}

function disposeTree(root: THREE.Object3D): void {
  root.traverse((object) => {
    if (object instanceof THREE.Mesh) {
      object.geometry.dispose();
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose();
    }
  });
}

function MeshLayer({ jobId, view }: { jobId: string; view: StageView }) {
  const ref = view.refs[0];
  if (!ref) return <Notice>Bước này chưa có collision mesh.</Notice>;
  return <CollisionMeshCanvas url={jobArtifactContentUrl(jobId, ref)} />;
}

/**
 * Collision mesh canonical (mét, Z-up, sàn z = 0) trong three.js. `children` vẽ trong cùng
 * khung Z-up (vd hộp vật thể ứng viên); mesh và material được giải phóng khi unmount/đổi URL.
 */
export function CollisionMeshCanvas({ url, children }: { url: string; children?: ReactNode }) {
  const [state, setState] = useState<{ root?: THREE.Group; error?: string; triangles?: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let root: THREE.Group | undefined;
    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Artifact HTTP ${response.status}`);
        const bytes = await response.arrayBuffer();
        requireEmbeddedGlb(bytes);
        return new GLTFLoader().parseAsync(bytes, "");
      })
      .then((asset) => {
        root = asset.scene;
        if (controller.signal.aborted) return disposeTree(root);
        let triangles = 0;
        root.traverse((object) => {
          if (!(object instanceof THREE.Mesh)) return;
          object.material = new THREE.MeshStandardMaterial({ color: "#8aa4c8", flatShading: true, side: THREE.DoubleSide });
          const index = object.geometry.getIndex();
          triangles += (index ? index.count : object.geometry.getAttribute("position").count) / 3;
        });
        setState({ root, triangles });
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setState({ error: errorMessage(cause, "Không tải được lớp xem. Hãy thử lại.") });
      });
    return () => {
      controller.abort();
      if (root) disposeTree(root);
    };
  }, [url]);

  // Mesh canonical Z-up; three.js Y-up → xoay -90° quanh X một lần ở group cha.
  const rotation = useMemo(() => [-Math.PI / 2, 0, 0] as [number, number, number], []);
  if (state?.error) return <Notice tone="rust">Không đọc được collision mesh: {state.error}</Notice>;
  if (!state?.root) {
    return (
      <p className="flex h-full items-center justify-center gap-2 text-sm text-paper/80" role="status">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tải collision mesh…
      </p>
    );
  }
  return (
    <>
      <Canvas camera={{ position: [8, 10, 12], fov: 50 }} gl={{ antialias: true }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[10, 20, 10]} intensity={0.9} />
        <group rotation={rotation}>
          <primitive object={state.root} dispose={null} />
          {children}
        </group>
        <Grid args={[40, 40]} cellSize={1} sectionSize={5} infiniteGrid fadeDistance={60} />
        <OrbitControls makeDefault />
      </Canvas>
      <p className="absolute bottom-3 left-3 rounded-md bg-viewport/80 px-2 py-1 text-xs text-paper/80">
        {state.triangles?.toLocaleString("vi-VN")} tam giác · lưới 1 m, sàn z = 0
      </p>
    </>
  );
}
