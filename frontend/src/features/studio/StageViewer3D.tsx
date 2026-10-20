"use client";

import { errorMessage } from "@/lib/ui-error";

import { Canvas } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
import { Loader2, Maximize, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { Notice } from "@/components/studio/primitives";
import { requireEmbeddedGlb } from "@/features/viewer/GlbArtifact";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import {
  INITIAL_RUNTIME,
  PlayCanvasScene,
  playCanvasErrorMessage,
  usePlayCanvasCapability,
  type ViewerControls,
} from "@/features/viewer/PlayCanvasScene";
import { recordingCameraPose, type SourceFrame } from "@/features/viewer/source-frame";
import { themeColor } from "@/lib/theme";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import { cn } from "@/lib/cn";
import type { StageView } from "@/lib/contracts/studio";
import { viewerRenderer } from "@/features/viewer/renderer-setting";
import { QuickViewButton } from "@/features/viewer/QuickViewButton";
import { useQuickView } from "@/features/viewer/useQuickView";

/** Lớp cần thư viện 3D (3DGS, lưới va chạm, khung hệ mét); tải động để bước Frames/Cameras không kéo three/PlayCanvas (T-065). */
export function Stage3DLayer({ jobId, view, views }: { jobId: string; view: StageView; views: StageView[] }) {
  // Lớp hệ mét dùng chung scene: 3DGS màu + collision mesh phủ lên, cùng hệ Z-up.
  const metric = views.find((item) => item.kind === "gaussian" && item.unit === "meter");
  const mesh = views.find((item) => item.kind === "mesh");
  // T-065: bước Collision mesh chỉ tải lưới (0,1–1 MB); SOG hệ mét (hàng chục MB) chỉ tải khi người dùng muốn xem kèm.
  if (metric?.refs[0] && view === mesh) return <MeshStepLayer jobId={jobId} mesh={mesh} metric={metric} />;
  if (metric?.refs[0] && (view === metric || view === mesh)) {
    return (
      <><p className="absolute bottom-3 left-3 z-20 rounded-md bg-viewport-deep/90 px-3 py-1 text-xs text-on-dark">
        Kết quả tái dựng trước khi chỉnh sửa vật thể
      </p><MetricSceneView
        jobId={jobId}
        visual={metric.refs[0]}
        collision={mesh?.refs[0]}
        reconstruction
        cameras={metric.cameras}
        defaultLayers={{ splat: true, collision: view === mesh, boxes: false }}
        lidarOverlay={metric.lidar_overlay ?? null}
      /></>
    );
  }
  if (view.kind === "gaussian") {
    // 3DGS Brush ở hệ SfM của COLMAP: cùng hệ với quỹ đạo camera của bước ước lượng camera.
    const sfm = views.find((item) => item.kind === "cameras")?.cameras ?? [];
    return <GaussianLayer jobId={jobId} view={view} cameras={view.cameras.length ? view.cameras : sfm} />;
  }
  return <MeshLayer jobId={jobId} view={view} />;
}

function GaussianLayer({ jobId, view, cameras }: { jobId: string; view: StageView; cameras: StageView["cameras"] }) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const [viewerControls, setViewerControls] = useState<ViewerControls | null>(null);
  const sourceFrame: SourceFrame = view.unit === "meter" ? "z_up" : "colmap";
  const [wheelFactor, setWheelFactor] = useState(2);
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const handleApp = useCallback((_app: unknown, controls?: ViewerControls) => {
    setViewerControls(controls ?? null);
  }, []);
  const displayRotation = view.unit === "arbitrary" ? view.display_rotation_xyzw ?? undefined : undefined;
  const initialCamera = useMemo(() => recordingCameraPose(sourceFrame, cameras, 60, displayRotation), [sourceFrame, cameras, displayRotation]);
  const ref = view.refs[0];
  const quickView = useQuickView(jobId, ref ?? null);
  if (!ref) return <Notice>Bước này chưa có file 3DGS.</Notice>;
  if (!quickView.settled) return <p role="status" className="p-6 text-sm text-on-dark/80">Đang tải bản xem 3DGS…</p>;
  if (capability === "failed" || capability === "unavailable") {
    return <p className="grid size-full place-items-center text-sm text-on-dark/80">{playCanvasErrorMessage(capability)}</p>;
  }
  return (
    <PlayCanvasScene
      contentUrl={quickView.url}
      contentFilename={ref.artifact_uri.split("/").pop() ?? "scene.sog"}
      renderer={viewerRenderer()}
      showControls
      mode="VISUAL"
      capability={capability}
      onFailed={fail}
      onRuntime={setRuntime}
      sourceFrame={sourceFrame}
      displayRotation={displayRotation}
      cameras={cameras}
      wheelFactor={wheelFactor}
      initialCamera={initialCamera}
      initialCameraMode="fly"
      onApp={handleApp}
      extraControls={
        <div
          className="sse-buttonGroup flex items-center shrink-0 border border-line-dark"
          onPointerDown={(e) => e.stopPropagation()}
        >
          <QuickViewButton view={quickView} />
          <button
            type="button"
            className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors disabled:opacity-40"
            onClick={() => viewerControls?.frameScene()}
            disabled={!runtime.loaded}
            title="Toàn cảnh (F)"
            aria-label="Toàn cảnh"
          >
            <Maximize className="size-4" aria-hidden />
          </button>
          <button
            type="button"
            className="sse-controlButton flex items-center justify-center text-on-dark/80 hover:text-on-dark transition-colors disabled:opacity-40"
            onClick={() => viewerControls?.resetCamera()}
            disabled={!runtime.loaded}
            title="Về vị trí ban đầu (R)"
            aria-label="Về vị trí ban đầu"
          >
            <RotateCcw className="size-4" aria-hidden />
          </button>
          <div className="flex items-center gap-0.5 border-l border-line-dark px-1.5 text-xs text-on-dark/80">
            <span className="text-[11px] text-on-dark/60 select-none mr-0.5">Zoom:</span>
            {[1, 2, 4].map((factor) => (
              <button
                key={factor}
                type="button"
                onClick={() => setWheelFactor(factor)}
                className={cn(
                  "rounded px-1.5 py-0.5 text-xs transition-colors",
                  wheelFactor === factor
                    ? "bg-ember-soft text-ember-strong font-medium"
                    : "text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10",
                )}
                title={`Tốc độ zoom ${factor === 1 ? "chuẩn (×1)" : `nhanh (×${factor})`}`}
              >
                {factor}×
              </button>
            ))}
          </div>
        </div>
      }
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

function MeshStepLayer({ jobId, mesh, metric }: { jobId: string; mesh: StageView; metric: StageView }) {
  const [withSplat, setWithSplat] = useState(false);
  if (withSplat && metric.refs[0]) {
    return (
      <MetricSceneView
        jobId={jobId}
        visual={metric.refs[0]}
        collision={mesh.refs[0]}
        reconstruction
        cameras={metric.cameras}
        defaultLayers={{ splat: true, collision: true, boxes: false }}
        lidarOverlay={metric.lidar_overlay ?? null}
      />
    );
  }
  return (
    <>
      <button
        type="button"
        onClick={() => setWithSplat(true)}
        className="absolute top-3 right-3 z-20 rounded-md bg-viewport-deep/90 px-3 py-1.5 text-xs text-on-dark hover:bg-viewport-deep"
      >
        Hiện kèm 3DGS
      </button>
      <MeshLayer jobId={jobId} view={mesh} />
    </>
  );
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
          object.material = new THREE.MeshStandardMaterial({ color: themeColor("--studio-geometry", "#2f7ea8"), flatShading: true, side: THREE.DoubleSide });
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
      <p className="flex h-full items-center justify-center gap-2 text-sm text-on-dark/80" role="status">
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
      <p className="absolute bottom-3 left-3 rounded-md border border-line-dark bg-viewport-deep/85 px-2 py-1 text-xs text-on-dark/80">
        {state.triangles?.toLocaleString("vi-VN")} tam giác · lưới 1 m, sàn z = 0
      </p>
    </>
  );
}
