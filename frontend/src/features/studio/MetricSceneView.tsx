"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { Notice } from "@/components/studio/primitives";
import {
  PlayCanvasScene,
  usePlayCanvasCapability,
  type ViewerAnnotation,
  type ViewerAppLike,
  type ViewerControls,
} from "@/features/viewer/PlayCanvasScene";
import { SceneOverlay, type OverlayBox } from "@/features/viewer/scene-overlay";
import {
  objectViewPose,
  recordingCameraPose,
  toDisplay,
  type CameraMarkerLike,
} from "@/features/viewer/source-frame";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import { cn } from "@/lib/cn";

interface Ref {
  artifact_uri: string;
  artifact_checksum: string;
}

/**
 * Scene hệ mét (Z-up, sàn z = 0) trong PlayCanvas: 3DGS có màu làm nền, collision mesh REC-05
 * và hộp vật thể phủ lên trong cùng scene graph. Camera mở tại camera quay đầu tiên.
 */
export function MetricSceneView({
  jobId,
  visual,
  collision,
  cameras,
  boxes = [],
  defaultLayers = { splat: true, collision: false, boxes: true },
  focus,
  onPickBox,
}: {
  jobId: string;
  visual: Ref;
  collision?: Ref;
  cameras: readonly CameraMarkerLike[];
  boxes?: readonly OverlayBox[];
  defaultLayers?: { splat: boolean; collision: boolean; boxes: boolean };
  /** Yêu cầu camera bay tới hộp `id`; `nonce` đổi để bay lại cùng vật. */
  focus?: { id: string; nonce: number };
  /** Người dùng bấm (không kéo) trúng một hộp trong 3D. */
  onPickBox?: (id: string) => void;
}) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const [overlay, setOverlay] = useState<SceneOverlay | null>(null);
  const [layers, setLayers] = useState(defaultLayers);
  const [collisionState, setCollisionState] = useState<{ triangles?: number; error?: string } | null>(null);
  const initialCamera = useMemo(() => recordingCameraPose("z_up", cameras), [cameras]);
  const contentUrl = jobArtifactContentUrl(jobId, visual);
  const collisionUrl = collision ? jobArtifactContentUrl(jobId, collision) : null;

  // Viewer gọi onApp(app) khi tạo và onApp(null) trước khi huỷ app → lớp phủ sống đúng bằng app.
  const overlayRef = useRef<SceneOverlay | null>(null);
  const controls = useRef<ViewerControls | null>(null);
  const onApp = useCallback((app: ViewerAppLike | null, next?: ViewerControls) => {
    overlayRef.current?.destroy();
    overlayRef.current = app ? new SceneOverlay(app) : null;
    controls.current = next ?? null;
    setOverlay(overlayRef.current);
  }, []);

  // Mỗi hộp là một điểm đến camera của viewer. Khoá theo hình học (id, tâm, kích thước), không theo
  // màu/trạng thái, để chọn hay xác nhận vật không tạo lại viewer; chỉ thêm/bớt vật mới tạo lại.
  const geometryKey = JSON.stringify(boxes.map((box) => [box.id, box.center, box.dimensions]));
  const annotationIds = useMemo(() => boxes.map((box) => box.id), [geometryKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const annotations = useMemo<ViewerAnnotation[]>(
    () =>
      boxes.map((box) => ({
        position: toDisplay("z_up", box.center),
        title: box.id,
        camera: objectViewPose(box.center, box.dimensions, cameras),
      })),
    [geometryKey, cameras], // eslint-disable-line react-hooks/exhaustive-deps
  );

  useEffect(() => {
    if (!focus) return;
    const index = annotationIds.indexOf(focus.id);
    if (index >= 0) controls.current?.select(index);
  }, [focus, annotationIds]);

  // Bấm = nhấn và nhả gần như tại chỗ, nhanh; kéo để xoay camera không tính là chọn.
  const press = useRef<{ x: number; y: number; time: number } | null>(null);
  const onPointerDown = (event: ReactPointerEvent) => {
    press.current = { x: event.clientX, y: event.clientY, time: event.timeStamp };
  };
  const onPointerUp = (event: ReactPointerEvent) => {
    const start = press.current;
    press.current = null;
    if (!start || !overlay || !onPickBox || !(event.target instanceof HTMLCanvasElement)) return;
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5 || event.timeStamp - start.time > 400) return;
    const rect = event.target.getBoundingClientRect();
    const id = overlay.pick(event.clientX - rect.left, event.clientY - rect.top);
    if (id) onPickBox(id);
  };

  useEffect(() => {
    if (!overlay || !collisionUrl) return;
    let active = true;
    overlay.loadCollision(collisionUrl, 0.3).then(
      (triangles) => active && setCollisionState({ triangles }),
      (error: unknown) => active && setCollisionState({ error: error instanceof Error ? error.message : String(error) }),
    );
    return () => {
      active = false;
    };
  }, [overlay, collisionUrl]);

  useEffect(() => {
    if (!overlay) return;
    overlay.setSplatVisible(layers.splat);
    // Không có 3DGS phía sau thì mesh đục cho dễ đọc hình khối.
    overlay.setCollision(layers.collision, layers.splat ? 0.3 : 1);
    overlay.setBoxes(layers.boxes ? boxes : []);
  }, [overlay, layers, boxes, collisionState]);

  if (capability === "failed" || capability === "unavailable") {
    return <Notice tone="rust">Trình duyệt không render được 3DGS (cần WebGL2/WebGPU).</Notice>;
  }
  const toggle = (key: keyof typeof layers, label: string, disabled = false) => (
    <label className={cn("flex items-center gap-1.5", disabled && "opacity-50")}>
      <input
        type="checkbox"
        checked={layers[key]}
        disabled={disabled}
        onChange={(event) => setLayers({ ...layers, [key]: event.target.checked })}
      />
      {label}
    </label>
  );
  return (
    <div className="relative size-full" onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
      <PlayCanvasScene
        contentUrl={contentUrl}
        contentFilename={visual.artifact_uri.split("/").pop() ?? "scene.sog"}
        renderer="webgl"
        showControls
        mode="VISUAL"
        capability={capability}
        onFailed={fail}
        sourceFrame="z_up"
        initialCamera={initialCamera}
        annotations={annotations}
        onApp={onApp}
      />
      <div className="absolute top-3 left-3 flex flex-wrap gap-3 rounded-md bg-viewport/80 px-3 py-1.5 text-xs text-paper/90">
        {toggle("splat", "3DGS màu")}
        {toggle("collision", "Collision mesh", !collisionUrl)}
        {toggle("boxes", "Hộp vật thể", !boxes.length)}
      </div>
      <p className="absolute bottom-3 left-3 rounded-md bg-viewport/80 px-2 py-1 text-xs text-paper/80">
        Hệ mét, sàn z = 0 · mở tại camera quay đầu tiên · kéo chuột để xoay, cuộn để zoom, chế độ bay (WASD) ở góc phải
        {collisionState?.triangles ? ` · collision ${Math.round(collisionState.triangles).toLocaleString("vi-VN")} tam giác` : ""}
        {collisionState?.error ? ` · không nạp được collision: ${collisionState.error}` : ""}
      </p>
    </div>
  );
}
