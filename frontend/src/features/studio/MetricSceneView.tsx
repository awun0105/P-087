"use client";

import type { AppBase } from "playcanvas";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { Copy, Eye, EyeOff, Hand, Maximize, Move3d, PersonStanding, RotateCcw, RotateCw, Trash2, X } from "lucide-react";
import { Notice } from "@/components/studio/primitives";
import {
  INITIAL_RUNTIME,
  PlayCanvasScene,
  playCanvasErrorMessage,
  usePlayCanvasCapability,
  type ViewerAnnotation,
  type ViewerAppLike,
  type ViewerControls,
} from "@/features/viewer/PlayCanvasScene";
import { SceneOverlay, type GizmoMode, type OverlayBox, type OverlayObject } from "@/features/viewer/scene-overlay";
import { ThirdPersonRig } from "@/features/viewer/third-person";
import { browserPhysicsBlocker, usePhysicsPlay, type PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";
import {
  objectViewPose,
  recordingCameraPose,
  toDisplay,
  type CameraMarkerLike,
  type SourceFrame,
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
  sceneRevision,
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
  placement = null,
  selectMode = true,
  onToggleSelectMode,
  selectedObject = null,
  tool = "none",
  onTool,
  onDuplicate,
  onToggleVisibility,
  onDelete,
  onDeselect,
}: {
  jobId: string;
  visual: Ref;
  collision?: Ref;
  sceneRevision?: string;
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
  /**
   * Chế độ đặt vật bằng chuột: hộp xem trước kích thước `dimensions` chạy theo con trỏ trên sàn, bấm để
   * đặt (`onPlace` nhận điểm sàn hệ Z-up mét), Esc để huỷ. null = không đặt vật.
   */
  placement?: { label: string; dimensions: [number, number, number]; onPlace: (point: [number, number, number]) => void; onCancel: () => void } | null;
  /** Chế độ chọn vật bằng bàn tay (bật/tắt). */
  selectMode?: boolean;
  onToggleSelectMode?: () => void;
  /** Vật thể đang chọn và metadata thao tác nhanh. */
  selectedObject?: {
    id: string;
    name: string;
    viewportHidden: boolean;
    canTransform: boolean;
  } | null;
  /** Chế độ công cụ gizmo hiện tại. */
  tool?: GizmoMode | "none";
  onTool?: (tool: GizmoMode | "none") => void;
  /** Nhân bản vật đang chọn. */
  onDuplicate?: () => void;
  /** Ẩn/hiện vật trong viewport, không ghi SceneIR. */
  onToggleVisibility?: () => void;
  /** Xoá vật đang chọn. */
  onDelete?: () => void;
  /** Bỏ chọn vật. */
  onDeselect?: () => void;
}) {
  const [capability, setCapability] = usePlayCanvasCapability();
  const fail = useCallback(() => setCapability("failed"), [setCapability]);
  const [overlay, setOverlay] = useState<SceneOverlay | null>(null);
  const [layers, setLayers] = useState({ ...defaultLayers, lidar: false });
  const [, setLidarState] = useState<{ points?: number; error?: string } | null>(null);
  const lidarUrl = lidarOverlay ? jobLidarOverlayUrl(jobId, lidarOverlay) : null;
  const [collisionState, setCollisionState] = useState<{ triangles?: number; error?: string } | null>(null);
  const initialCamera = useMemo(() => recordingCameraPose("z_up", cameras), [cameras]);
  const contentUrl = jobArtifactContentUrl(jobId, visual);
  const collisionUrl = collision ? (sceneRevision ? jobWalkCollisionUrl(jobId, collision, [], sceneRevision, "canonical") : jobArtifactContentUrl(jobId, collision)) : null;
  const walkCollisionUrl = collision ? jobWalkCollisionUrl(jobId, collision, [], sceneRevision) : null;
  const physicsBlocker = browserPhysicsBlocker(physicsObjects);
  const physicsIdentity = JSON.stringify([physicsObjects, walkCollisionUrl]);
  const [physicsFailure, setPhysicsFailure] = useState<{ identity: string; message: string } | null>(null);
  const [walkCollisionError, setWalkCollisionError] = useState<string | null>(null);
  const [runtime, setRuntime] = useState(INITIAL_RUNTIME);
  const [viewerControls, setViewerControls] = useState<ViewerControls | null>(null);
  const sourceFrame: SourceFrame = "z_up";
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

  // Mỗi hộp là một điểm đến camera của viewer. PlayCanvasScene cập nhật danh sách này tại chỗ (không tạo lại
  // viewer), nên lọc/xác nhận/loại/nhân bản/dời vật không tải lại 3DGS. Khoá theo id + hình học, bỏ qua màu.
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
  const idsRef = useRef(annotationIds);
  useEffect(() => {
    idsRef.current = annotationIds;
  }, [annotationIds]);

  useEffect(() => {
    if (!focus) return;
    const index = idsRef.current.indexOf(focus.id);
    if (index >= 0) controls.current?.select(index);
  }, [focus]);

  // Bấm = nhấn và nhả gần như tại chỗ, nhanh; kéo để xoay camera không tính là chọn.
  const press = useRef<{ x: number; y: number; time: number } | null>(null);
  const onPointerDown = (event: ReactPointerEvent) => {
    press.current = { x: event.clientX, y: event.clientY, time: event.timeStamp };
  };
  const canvasPoint = (event: ReactPointerEvent): [number, number] | null => {
    if (!(event.target instanceof HTMLCanvasElement)) return null;
    const rect = event.target.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  };
  const onPointerMove = (event: ReactPointerEvent) => {
    if (!placement || !overlay) return;
    const point = canvasPoint(event);
    overlay.setGhost(placement.dimensions, point ? overlay.floorPoint(point[0], point[1]) : null);
  };
  const onPointerUp = (event: ReactPointerEvent) => {
    const start = press.current;
    press.current = null;
    const point = canvasPoint(event);
    if (!start || !overlay || !point) return;
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5 || event.timeStamp - start.time > 400) return;
    if (placement) {
      // Đang đặt vật: bấm vào sàn thì đặt tại đó; trượt sàn (trời/xa) thì bỏ qua, vẫn ở chế độ đặt.
      if (event.button !== 0) return;
      const floor = overlay.floorPoint(point[0], point[1]);
      if (floor) placement.onPlace(floor);
      return;
    }
    if (!selectMode || !onPickBox) return;
    const id = overlay.pick(point[0], point[1]);
    if (id) onPickBox(id);
    else onDeselect?.();
  };
  const onPointerLeave = () => {
    if (placement) overlay?.setGhost(null);
  };

  // Hết chế độ đặt (đặt xong/huỷ/đổi vật) thì ẩn hộp xem trước; Esc huỷ đặt hoặc bỏ chọn vật.
  const placementDims = placement?.dimensions;
  const cancelPlacement = placement?.onCancel;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (placementDims) cancelPlacement?.();
        else if (selectedObject) onDeselect?.();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (placementDims) overlay?.setGhost(null);
    };
  }, [placementDims, cancelPlacement, selectedObject, onDeselect, overlay]);

  useEffect(() => {
    if (!overlay || !collisionUrl) return;
    let active = true;
    rig?.setCollision(null);
    queueMicrotask(() => { if (active) setCollisionState(null); });
    overlay.loadCollision(collisionUrl, 0.3).then(
      (triangles) => active && setCollisionState({ triangles }),
      (error: unknown) => active && setCollisionState({ error: error instanceof Error ? error.message : String(error) }),
    );
    return () => {
      active = false;
    };
  }, [overlay, collisionUrl, rig]);

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
  useEffect(() => {
    if (physics.status.state !== "failed") return;
    const message = physics.status.message;
    queueMicrotask(() => setPhysicsFailure({ identity: physicsIdentity, message }));
  }, [physics.status, physicsIdentity]);
  const walkBlocker = physicsBlocker ?? (physicsFailure?.identity === physicsIdentity ? physicsFailure.message : null);

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
    return <Notice tone="rust">{playCanvasErrorMessage(capability)}</Notice>;
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
    <div
      className={cn("relative size-full", placement && "[&_canvas]:cursor-crosshair")}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
    >
      {(walkBlocker || walkCollisionError) && <Notice tone="rust">Không thể dùng Walk: {walkBlocker ?? walkCollisionError}</Notice>}
      {placement && (
        <div
          role="status"
          className="pointer-events-auto absolute top-14 left-1/2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-md border border-ember bg-viewport-deep/90 px-3 py-1.5 text-xs text-on-dark shadow-xl backdrop-blur-md"
        >
          <span>
            Đặt <strong>{placement.label}</strong>: di chuột trên sàn và bấm để đặt · Esc để huỷ
          </span>
          <button
            type="button"
            onClick={placement.onCancel}
            onPointerDown={(event) => event.stopPropagation()}
            className="rounded px-1.5 py-0.5 text-on-dark/70 hover:bg-on-dark/10 hover:text-on-dark"
          >
            Huỷ
          </button>
        </div>
      )}
      <PlayCanvasScene
        contentUrl={contentUrl}
        contentFilename={visual.artifact_uri.split("/").pop() ?? "scene.sog"}
        renderer="webgl"
        showControls
        mode="VISUAL"
        capability={capability}
        onFailed={fail}
        sourceFrame={sourceFrame}
        cameras={cameras}
        initialCamera={initialCamera}
        initialCameraMode="fly"
        annotations={annotations}
        onApp={onApp}
        collisionUrl={walkBlocker || physics.status.state === "failed" ? null : walkCollisionUrl}
        onCollisionError={setWalkCollisionError}
        onRuntime={setRuntime}
        wheelFactor={wheelFactor}
        extraControls={
          <div
            className="sse-buttonGroup flex items-center shrink-0 border border-line-dark"
            onPointerDown={(e) => e.stopPropagation()}
          >
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
            <button
              type="button"
              className={cn(
                "sse-controlButton flex items-center justify-center transition-colors",
                thirdPerson && walking
                  ? "bg-ember-soft text-ember-strong font-medium"
                  : "text-on-dark/80 hover:text-on-dark",
                (!runtime.loaded || !walking) && "opacity-40 cursor-not-allowed",
              )}
              onClick={() => setThirdPerson(!thirdPerson)}
              disabled={!runtime.loaded || !walking}
              title={
                walking
                  ? "Góc nhìn thứ ba (nhìn từ sau lưng nhân vật)"
                  : "Chỉ dùng được trong chế độ Đi bộ (chuyển sang Đi bộ để bật)"
              }
              aria-label="Góc nhìn thứ ba"
              aria-pressed={Boolean(thirdPerson) && walking}
            >
              <PersonStanding className="size-4" aria-hidden />
            </button>
            {onToggleSelectMode && (
              <button
                type="button"
                className={cn(
                  "sse-controlButton flex items-center justify-center transition-all",
                  selectMode
                    ? "sse-active bg-ember-soft text-ember-strong font-medium ring-1 ring-ember shadow-[0_0_12px_var(--color-ember)]"
                    : "text-on-dark/80 hover:text-on-dark",
                  !runtime.loaded && "opacity-40 cursor-not-allowed",
                )}
                onClick={onToggleSelectMode}
                disabled={!runtime.loaded}
                title={
                  selectMode
                    ? "Chế độ chọn vật thể: Đang bật (bấm để tắt)"
                    : "Chế độ chọn vật thể: Đang tắt (bấm để bật chọn vật thể trong 3D)"
                }
                aria-label="Chọn vật thể"
                aria-pressed={selectMode}
              >
                <Hand className={cn("size-4 transition-transform", selectMode && "drop-shadow-[0_0_6px_var(--color-ember)] scale-105")} aria-hidden />
              </button>
            )}
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
      {selectedObject && (
        <div
          role="toolbar"
          aria-label="Thao tác vật thể đang chọn"
          className="pointer-events-auto absolute bottom-14 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-lg border border-line-dark bg-viewport-deep/95 px-3 py-1.5 text-xs text-on-dark shadow-2xl backdrop-blur-md"
          onPointerDown={(e) => e.stopPropagation()}
        >
          <div className="flex items-center gap-1.5 border-r border-line-dark pr-2.5">
            <span className="size-2 rounded-full bg-ember shrink-0" aria-hidden />
            <span className="max-w-[140px] truncate font-medium text-ember-strong" title={selectedObject.name}>
              {selectedObject.name}
            </span>
          </div>

          {selectedObject.canTransform && (
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onTool?.(tool === "translate" ? "none" : "translate")}
                className={cn(
                  "flex items-center gap-1 rounded px-2 py-1 transition-colors",
                  tool === "translate"
                    ? "bg-ember-soft text-ember-strong font-medium"
                    : "text-on-dark/80 hover:bg-on-dark/10 hover:text-on-dark",
                )}
                title="Dịch chuyển vật (G)"
                aria-pressed={tool === "translate"}
              >
                <Move3d className="size-3.5" aria-hidden />
                <span>Dịch</span>
              </button>
              <button
                type="button"
                onClick={() => onTool?.(tool === "rotate" ? "none" : "rotate")}
                className={cn(
                  "flex items-center gap-1 rounded px-2 py-1 transition-colors",
                  tool === "rotate"
                    ? "bg-ember-soft text-ember-strong font-medium"
                    : "text-on-dark/80 hover:bg-on-dark/10 hover:text-on-dark",
                )}
                title="Xoay vật (R)"
                aria-pressed={tool === "rotate"}
              >
                <RotateCw className="size-3.5" aria-hidden />
                <span>Xoay</span>
              </button>
            </div>
          )}

          {onDuplicate && (
            <button
              type="button"
              onClick={onDuplicate}
              className="flex items-center gap-1 rounded px-2 py-1 text-on-dark/80 hover:bg-on-dark/10 hover:text-on-dark transition-colors"
              title="Nhân bản vật thể"
            >
              <Copy className="size-3.5" aria-hidden />
              <span>Nhân bản</span>
            </button>
          )}

          {onToggleVisibility && (
            <button
              type="button"
              onClick={onToggleVisibility}
              className={cn(
                "flex items-center gap-1 rounded px-2 py-1 transition-colors",
                selectedObject.viewportHidden
                  ? "bg-rust/20 text-rust font-medium"
                  : "text-on-dark/80 hover:bg-on-dark/10 hover:text-on-dark",
              )}
              title={!selectedObject.viewportHidden ? "Ẩn trên màn hình" : "Hiện trên màn hình"}
            >
              {!selectedObject.viewportHidden ? (
                <>
                  <EyeOff className="size-3.5" aria-hidden />
                  <span>Ẩn</span>
                </>
              ) : (
                <>
                  <Eye className="size-3.5" aria-hidden />
                  <span>Hiện</span>
                </>
              )}
            </button>
          )}

          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              className="flex items-center gap-1 rounded px-2 py-1 text-rust hover:bg-rust/10 transition-colors"
              title="Xoá vật thể"
            >
              <Trash2 className="size-3.5" aria-hidden />
              <span>Xóa</span>
            </button>
          )}

          <div className="border-l border-line-dark pl-1">
            <button
              type="button"
              onClick={onDeselect}
              className="rounded p-1 text-on-dark/60 hover:bg-on-dark/10 hover:text-on-dark transition-colors"
              title="Bỏ chọn (Esc)"
              aria-label="Bỏ chọn"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        </div>
      )}
      <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 flex max-w-[calc(100%-1.5rem)] flex-col items-center gap-2 pointer-events-none">
        <div className="pointer-events-auto flex flex-wrap gap-3 rounded-md border border-line-dark bg-viewport-deep/85 px-3 py-1.5 text-xs text-on-dark/90 backdrop-blur-md shadow-lg">
          {toggle("splat", "3DGS màu")}
          {toggle("collision", "Collision mesh", !collisionUrl)}
          {toggle("boxes", "Khung vật thể", !boxes.length)}
          {lidarUrl && toggle("lidar", "Đám mây LiDAR")}
        </div>
        {walking && physics.status.state !== "off" && (
          <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-md border border-line-dark bg-viewport-deep/85 px-3 py-1.5 text-xs text-on-dark/90 backdrop-blur-md shadow-lg" role="status">
            {physics.status.state === "loading" && "Đang dựng vật lý cho vật động…"}
            {physics.status.state === "ready" && `Đi vào vật để đẩy · ${physics.status.objects} vật động`}
            {physics.status.state === "failed" && `Không bật được vật lý: ${physics.status.message}`}
            {physics.status.state === "ready" && (
              <button type="button" onClick={physics.reset} className="rounded px-2 py-0.5 hover:bg-on-dark/10">Đặt lại vị trí vật</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
