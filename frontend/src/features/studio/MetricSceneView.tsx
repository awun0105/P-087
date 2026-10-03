"use client";

import type { AppBase } from "playcanvas";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { Notice } from "@/components/studio/primitives";
import { CameraToolbar } from "@/features/viewer/CameraToolbar";
import {
  INITIAL_RUNTIME,
  PlayCanvasScene,
  usePlayCanvasCapability,
  type ViewerAnnotation,
  type ViewerAppLike,
  type ViewerControls,
} from "@/features/viewer/PlayCanvasScene";
import { SceneOverlay, type GizmoMode, type OverlayBox, type OverlayObject } from "@/features/viewer/scene-overlay";
import { ThirdPersonRig } from "@/features/viewer/third-person";
import { usePhysicsPlay, type PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";
import {
  objectViewPose,
  recordingCameraPose,
  toDisplay,
  type CameraMarkerLike,
} from "@/features/viewer/source-frame";
import { jobArtifactContentUrl, jobLidarOverlayUrl, jobWalkCollisionUrl } from "@/lib/api/endpoints";
import { cn } from "@/lib/cn";

const EMPTY_OBJECTS: readonly OverlayObject[] = [];
const NO_PHYSICS: readonly PhysicsObjectInput[] = [];

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
  objects = EMPTY_OBJECTS,
  gizmo = null,
  onTransform,
  defaultLayers = { splat: true, collision: false, boxes: true },
  lidarOverlay = null,
  physicsObjects = NO_PHYSICS,
  focus,
  onPickBox,
}: {
  jobId: string;
  visual: Ref;
  collision?: Ref;
  cameras: readonly CameraMarkerLike[];
  boxes?: readonly OverlayBox[];
  /** Scene theo vật (pipeline v2): mỗi vật một khối Gaussian riêng, transform lấy từ SceneIR. */
  objects?: readonly OverlayObject[];
  /** Vật đang gắn gizmo và chế độ; null = không có gizmo. */
  gizmo?: { id: string; mode: GizmoMode } | null;
  /** Người dùng thả gizmo: transform mới của vật (mét, Z-up) để ghi revision. */
  onTransform?: (id: string, position: [number, number, number], rotation: [number, number, number, number]) => void;
  defaultLayers?: { splat: boolean; collision: boolean; boxes: boolean };
  /** Khoá lớp LiDAR đã căn chỉnh của scene (từ `StageView.lidar_overlay`); null = scene không có LiDAR. */
  lidarOverlay?: string | null;
  /** Vật động (SceneIR `physics.dynamic`): khi Đi bộ, người đi đẩy được chúng (vật lý chỉ ở trình duyệt). */
  physicsObjects?: readonly PhysicsObjectInput[];
  /** Yêu cầu camera bay tới hộp `id`; `nonce` đổi để bay lại cùng vật. */
  focus?: { id: string; nonce: number };
  /** Người dùng bấm (không kéo) trúng một hộp trong 3D. */
  onPickBox?: (id: string) => void;
}) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const [overlay, setOverlay] = useState<SceneOverlay | null>(null);
  const [layers, setLayers] = useState({ ...defaultLayers, lidar: false });
  const [lidarState, setLidarState] = useState<{ points?: number; error?: string } | null>(null);
  const lidarUrl = lidarOverlay ? jobLidarOverlayUrl(jobId, lidarOverlay) : null;
  const [collisionState, setCollisionState] = useState<{ triangles?: number; error?: string } | null>(null);
  const initialCamera = useMemo(() => recordingCameraPose("z_up", cameras), [cameras]);
  const contentUrl = jobArtifactContentUrl(jobId, visual);
  const collisionUrl = collision ? jobArtifactContentUrl(jobId, collision) : null;
  // Viewer đọc toạ độ đỉnh thô của lưới va chạm, nên chế độ đi bộ dùng bản đã xoay sang không gian hiển thị.
  // Vùng gốc của vật động được khoét khỏi lưới đi bộ; khoá theo tập id để chỉ tạo lại viewer khi tập này đổi.
  const dynamicKey = physicsObjects.map((item) => item.id).sort().join(",");
  const walkCollisionUrl = useMemo(
    () => (collision ? jobWalkCollisionUrl(jobId, collision, dynamicKey ? dynamicKey.split(",") : []) : null),
    [jobId, collision, dynamicKey],
  );
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const [viewerControls, setViewerControls] = useState<ViewerControls | null>(null);
  const [wheelFactor, setWheelFactor] = useState(2);
  const [thirdPerson, setThirdPerson] = useState(false);

  // Viewer gọi onApp(app) khi tạo và onApp(null) trước khi huỷ app → lớp phủ sống đúng bằng app.
  const overlayRef = useRef<SceneOverlay | null>(null);
  const controls = useRef<ViewerControls | null>(null);
  const rigRef = useRef<ThirdPersonRig | null>(null);
  const [rig, setRig] = useState<ThirdPersonRig | null>(null);
  const [viewerApp, setViewerApp] = useState<AppBase | null>(null);
  const onApp = useCallback((app: ViewerAppLike | null, next?: ViewerControls) => {
    setViewerApp(app as unknown as AppBase | null);
    rigRef.current?.destroy();
    rigRef.current = app ? new ThirdPersonRig(app as unknown as AppBase) : null;
    setRig(rigRef.current);
    overlayRef.current?.destroy();
    overlayRef.current = app ? new SceneOverlay(app) : null;
    controls.current = next ?? null;
    setViewerControls(next ?? null);
    setOverlay(overlayRef.current);
  }, []);

  // Mỗi hộp là một điểm đến camera của viewer (chỉ khai báo được lúc tạo viewer). Khoá theo tập id,
  // không theo màu/trạng thái/vị trí: chọn, xác nhận hay dời vật không tạo lại viewer (tải lại 3DGS);
  // chỉ thêm/bớt vật mới tạo lại. Vật vừa dời giữ điểm bay tới của vị trí cũ cho tới lần tạo lại kế.
  const geometryKey = JSON.stringify(boxes.map((box) => box.id));
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

  // Góc nhìn thứ ba chỉ có nghĩa khi đang đi bộ; lưới va chạm (nạp xong mới có) giữ camera không lùi xuyên tường.
  const walking = runtime.cameraMode === "walk";
  useEffect(() => {
    // Trích đỉnh của lưới va chạm một lần mỗi khi lưới nạp xong, không lặp lại mỗi lần bật/tắt.
    rig?.setCollision(overlay?.collisionPositions() ?? null);
  }, [rig, overlay, collisionState]);
  useEffect(() => {
    if (!rig) return;
    rig.setActive(thirdPerson && walking);
    return () => rig.setActive(false);
  }, [rig, thirdPerson, walking]);

  const physics = usePhysicsPlay({
    app: viewerApp,
    overlay,
    walking,
    collisionUrl: walkCollisionUrl,
    objects: physicsObjects,
    overlayObjects: objects,
  });

  // Lớp LiDAR chỉ tải khi người dùng bật (vài MB); tắt thì giải phóng GPU, bật lại lấy từ cache của trình duyệt.
  const lidarWanted = layers.lidar && lidarUrl !== null;
  useEffect(() => {
    if (!overlay || !lidarWanted || !lidarUrl) return;
    const controller = new AbortController();
    fetch(lidarUrl, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const bytes = await response.arrayBuffer();
        if (bytes.byteLength === 0 || bytes.byteLength % 12 !== 0) throw new Error("dữ liệu điểm không hợp lệ");
        return new Float32Array(bytes);
      })
      .then((positions) => {
        if (controller.signal.aborted) return;
        setLidarState({ points: overlay.setPoints(positions) });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLidarState({ error: error instanceof Error ? error.message : String(error) });
      });
    return () => {
      controller.abort();
      overlay.setPoints(null);
    };
  }, [overlay, lidarWanted, lidarUrl]);

  useEffect(() => {
    if (!overlay) return;
    // Tắt lớp 3DGS thì ẩn cả Gaussian của vật (cùng một lớp hình).
    overlay.setObjects(objects.map((item) => ({ ...item, visible: item.visible && layers.splat })));
  }, [overlay, objects, layers.splat]);

  const transformed = useRef(onTransform);
  useEffect(() => {
    transformed.current = onTransform;
  }, [onTransform]);
  const gizmoId = gizmo?.id ?? null;
  const gizmoMode = gizmo?.mode ?? "translate";
  useEffect(() => {
    if (!overlay || !gizmoId) return;
    overlay.attachGizmo(gizmoId, gizmoMode, {
      onStart: () => controls.current?.setInputEnabled(false),
      onEnd: (id, position, rotation) => {
        controls.current?.setInputEnabled(true);
        transformed.current?.(id, position, rotation);
      },
    });
    return () => {
      overlay.detachGizmo();
      controls.current?.setInputEnabled(true);
    };
    // `objects` trong deps: gizmo gắn lại sau khi vật được tạo/đổi revision.
  }, [overlay, gizmoId, gizmoMode, objects]);

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
        collisionUrl={walkCollisionUrl}
        onRuntime={setRuntime}
        wheelFactor={wheelFactor}
      />
      <div className="absolute top-3 left-3 flex max-w-[calc(100%-1.5rem)] flex-col items-start gap-2">
        <div className="flex flex-wrap gap-3 rounded-md border border-line-dark bg-viewport-deep/85 px-3 py-1.5 text-xs text-on-dark/90">
          {toggle("splat", "3DGS màu")}
          {toggle("collision", "Collision mesh", !collisionUrl)}
          {toggle("boxes", "Khung vật thể", !boxes.length)}
          {lidarUrl && toggle("lidar", "Đám mây LiDAR")}
        </div>
        <CameraToolbar runtime={runtime} controls={viewerControls} wheelFactor={wheelFactor} onWheelFactor={setWheelFactor} thirdPerson={thirdPerson} onThirdPerson={setThirdPerson} />
        {walking && physics.status.state !== "off" && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-line-dark bg-viewport-deep/85 px-3 py-1.5 text-xs text-on-dark/90" role="status">
            {physics.status.state === "loading" && "Đang dựng vật lý cho vật động…"}
            {physics.status.state === "ready" && `Đi vào vật để đẩy · ${physics.status.objects} vật động`}
            {physics.status.state === "failed" && `Không bật được vật lý: ${physics.status.message}`}
            {physics.status.state === "ready" && (
              <button type="button" onClick={physics.reset} className="rounded px-2 py-0.5 hover:bg-on-dark/10">Đặt lại vị trí vật</button>
            )}
          </div>
        )}
      </div>
      <p className="absolute bottom-3 left-3 rounded-md border border-line-dark bg-viewport-deep/85 px-2 py-1 text-xs text-on-dark/80">
        Hệ mét, sàn z = 0 · mở tại camera quay đầu tiên
        {collisionState?.triangles ? ` · collision ${Math.round(collisionState.triangles).toLocaleString("vi-VN")} tam giác` : ""}
        {collisionState?.error ? ` · không nạp được collision: ${collisionState.error}` : ""}
        {layers.lidar && lidarState?.points ? ` · LiDAR ${lidarState.points.toLocaleString("vi-VN")} điểm` : ""}
        {layers.lidar && lidarState?.error ? ` · không nạp được LiDAR: ${lidarState.error}` : ""}
      </p>
    </div>
  );
}
