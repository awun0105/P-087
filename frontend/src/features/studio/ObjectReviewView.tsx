"use client";


import { errorMessage } from "@/lib/ui-error";

import dynamic from "next/dynamic";
import {
  Boxes,
  Check,
  ChevronDown,
  ChevronUp,
  Crosshair,
  Library,
  Loader2,
  Pencil,
  Plus,
  Tag,
  Undo2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent, useSyncExternalStore } from "react";
import { subscribeTheme, themeColor, themeKey } from "@/lib/theme";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import { ObjectifyNotice } from "@/features/studio/ObjectifyNotice";
import type { GizmoMode, OverlayBox, OverlayObject } from "@/features/viewer/scene-overlay";
import type { PhysicsObjectInput } from "@/features/viewer/usePhysicsPlay";
import { ApiError } from "@/lib/api/client";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import {
  addBoxObstacle,
  addCatalogObject,
  applyObjectAction,
  catalogPreviewUrl,
  getJobScene,
  getSceneCatalog,
  getStageViews,
  restoreSceneRevision,
  setObjectTransform,
  type ObjectAction,
  type SceneCatalog,
} from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { SceneIR, SceneObject } from "@/lib/contracts/api";
import type { StageView } from "@/lib/contracts/studio";

// Chỉ dùng khi scene không có 3DGS: tải three.js theo nhu cầu, không kéo vào mọi lần mở Studio.
const CollisionMeshCanvas = dynamic(() => import("@/features/studio/StageViewer").then((m) => m.CollisionMeshCanvas), { ssr: false });

/** Hình riêng của một vật trong viewer: Gaussian của vật tách từ scene, hoặc GLB của asset thư viện. */
function objectVisual(jobId: string, object: SceneObject, previews: ReadonlySet<string>): Pick<OverlayObject, "url" | "kind"> {
  if (object.visual_ref?.artifact_type === "ObjectGaussians") return { url: jobArtifactContentUrl(jobId, object.visual_ref), kind: "gsplat" };
  const family = object.provenance?.catalog_family;
  if (typeof family === "string" && previews.has(family)) return { url: catalogPreviewUrl(family), kind: "model" };
  return { url: null };
}

/** Trạng thái lưu SceneObject cho header scene (STUDIO_UX_SPEC.md Q5: mỗi thao tác là một revision). */
export type SaveState =
  | { status: "saved"; revision: string }
  | { status: "saving"; revision: string }
  | { status: "error"; revision: string; message: string; retry: () => void };

type Filter = "all" | "pending" | "confirmed" | "ignored";

const FILTERS: { value: Filter; label: string; match: (object: SceneObject) => boolean }[] = [
  { value: "all", label: "Chưa loại", match: (object) => !isIgnored(object) },
  { value: "pending", label: "Chờ xác nhận", match: (object) => object.state === "CANDIDATE" && !isIgnored(object) },
  { value: "confirmed", label: "Đã xác nhận", match: (object) => object.state === "CONFIRMED" },
  { value: "ignored", label: "Đã loại/xoá", match: isIgnored },
];

/**
 * Studio vật thể (ADR 0006, PRODUCT-07/07A, STUDIO_UX_SPEC.md P5): danh sách · viewport 3DGS hệ mét ·
 * inspector. Người dùng xác nhận/loại ứng viên, ẩn/đổi tên vật đã xác nhận hoặc thêm vật cản hộp.
 * Mỗi thao tác là một revision SceneIR mới ở backend; màn hình chỉ giữ revision vừa nhận, không tự
 * sửa scene ở client.
 */
export function ObjectReviewView({
  jobId,
  revision,
  onSaveState,
}: {
  jobId: string;
  /** Revision mới nhất nơi khác biết; khác revision đang giữ thì tải lại (tránh 409 khi thao tác). */
  revision?: string | null;
  onSaveState?: (state: SaveState) => void;
}) {
  const [scene, setScene] = useState<SceneIR | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [cameras, setCameras] = useState<StageView["cameras"]>([]);
  const [focus, setFocus] = useState<{ id: string; nonce: number } | undefined>();
  const [reload, setReload] = useState(0);
  const [tool, setTool] = useState<GizmoMode | "none">("none");
  const [selectMode, setSelectMode] = useState(true);
  const [catalog, setCatalog] = useState<SceneCatalog | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  /** Vật đang chờ đặt bằng chuột: kích thước hộp xem trước + lệnh ghi khi bấm sàn. */
  const [placing, setPlacing] = useState<{ label: string; dimensions: [number, number, number]; commit: (point: [number, number, number]) => void } | null>(null);
  const cancelPlacing = useCallback(() => setPlacing(null), []);
  const stale = Boolean(revision && scene && !busy && revision !== scene.scene_revision);

  /** Chọn và cho camera bay tới vật (từ danh sách hoặc nút trong inspector). */
  const flyTo = (id: string) => {
    setSelected(id);
    setFocus((previous) => ({ id, nonce: (previous?.nonce ?? 0) + 1 }));
    setRightCollapsed(false);
  };
  /** Chọn bằng cách bấm hộp trong 3D: đánh dấu và cuộn danh sách tới vật đó. */
  const selectFromScene = (id: string) => {
    setSelected(id);
    setRightCollapsed(false);
    document.getElementById(`object-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  useEffect(() => {
    const controller = new AbortController();
    getJobScene(jobId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setScene(result.data.scene);
        setError(null);
        onSaveState?.({ status: "saved", revision: result.data.scene.scene_revision });
      } else if (result.error.status === 404) setMissing(true);
      else setError(errorMessage(result.error));
    });
    return () => controller.abort();
  }, [jobId, reload, stale]); // eslint-disable-line react-hooks/exhaustive-deps -- onSaveState chỉ là kênh báo lên header

  useEffect(() => {
    const controller = new AbortController();
    // Camera quay hệ mét để mở scene tại góc camera đầu tiên; thiếu thì dùng camera mặc định.
    // Tách khỏi lần tải scene: camera không đổi khi sửa vật, tải lại sẽ tạo lại viewer 3D.
    getStageViews(jobId, controller.signal).then(
      (views) => setCameras(views.find((view) => view.kind === "gaussian" && view.unit === "meter")?.cameras ?? []),
      () => undefined,
    );
    return () => controller.abort();
  }, [jobId]);

  useEffect(() => {
    const controller = new AbortController();
    // Danh mục nhãn/asset không đổi theo scene: tải một lần; lỗi thì chỉ mất phần gán nhãn/thư viện.
    getSceneCatalog(controller.signal).then(setCatalog, () => undefined);
    return () => controller.abort();
  }, []);

  const previews = useMemo(() => new Set((catalog?.entries ?? []).filter((item) => item.has_preview).map((item) => item.family)), [catalog]);
  // Scene theo vật (pipeline v2): mỗi vật có Gaussian riêng. Vật đã loại/xoá hoặc đang ẩn không vẽ.
  const splats = useMemo<OverlayObject[]>(
    () =>
      (scene?.objects ?? []).map((object) => ({
        id: object.id,
        ...objectVisual(jobId, object, previews),
        position: object.transform.translation_xyz,
        rotation_xyzw: object.transform.rotation_quaternion_xyzw,
        visible: isPlaced(object),
      })),
    [scene, jobId, previews],
  );

  // Vật động (vật lý của SceneIR) đang đặt trong scene: khi Đi bộ, người đi đẩy được chúng (ADR 0010).
  const physicsObjects = useMemo<PhysicsObjectInput[]>(
    () =>
      (scene?.objects ?? [])
        .filter((object) => object.physics?.dynamic && object.active && isPlaced(object))
        .map((object) => ({
          id: object.id,
          position: object.transform.translation_xyz,
          rotation_xyzw: object.transform.rotation_quaternion_xyzw,
          colliderUrl:
            object.collider?.geometry_ref && object.collider.geometry_ref.artifact_uri.endsWith(".glb")
              ? jobArtifactContentUrl(jobId, object.collider.geometry_ref)
              : null,
          dimensions: object.primitive_dimensions_xyz_m ?? null,
          mass_kg: object.physics!.mass_kg ?? 10,
          friction: object.physics!.dynamic_friction,
          restitution: object.physics!.restitution,
        })),
    [scene, jobId],
  );

  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((item) => [item.value, scene?.objects.filter(item.match).length ?? 0])) as Record<Filter, number>,
    [scene],
  );
  const visibleObjects = useMemo(() => {
    const match = FILTERS.find((item) => item.value === filter)!.match;
    return scene?.objects.filter(match) ?? [];
  }, [scene, filter]);
  const theme = useSyncExternalStore(subscribeTheme, themeKey, () => "light:default");
  const boxes = useMemo<OverlayBox[]>(
    () =>
      visibleObjects
        .filter((object) => object.primitive_dimensions_xyz_m)
        .map((object) => ({
          id: object.id,
          center: object.transform.translation_xyz,
          rotation_xyzw: object.transform.rotation_quaternion_xyzw,
          dimensions: object.primitive_dimensions_xyz_m!,
          color: object.id === selected ? selectedColor() : stateColor(object),
          emphasized: object.id === selected,
          // Collider phân rã lồi bám theo hình vật; vật chỉ có hộp (thêm tay, asset thư viện) thì vẽ hộp.
          shapeUrl:
            object.collider?.geometry_ref && object.collider.geometry_ref.artifact_uri.endsWith(".glb")
              ? jobArtifactContentUrl(jobId, object.collider.geometry_ref)
              : null,
        })),
    // `theme` trong deps: đổi chế độ/bảng màu thì khung vật vẽ lại bằng màu mới.
    [visibleObjects, selected, jobId, theme], // eslint-disable-line react-hooks/exhaustive-deps
  );

  async function run(mutate: (revision: string) => Promise<{ scene: SceneIR }>) {
    if (!scene) return;
    const revision = scene.scene_revision;
    setBusy(true);
    setError(null);
    onSaveState?.({ status: "saving", revision });
    try {
      const next = (await mutate(revision)).scene;
      setScene(next);
      onSaveState?.({ status: "saved", revision: next.scene_revision });
    } catch (cause: unknown) {
      // 409: scene đã đổi ở lượt khác — phải tải revision mới trước khi ghi (§S06 recovery).
      const conflict = cause instanceof ApiError && cause.status === 409;
      const message = conflict
        ? "Scene đã đổi ở lượt khác. Tải bản mới rồi thao tác lại."
        : errorMessage(cause, "Thao tác thất bại");
      setError(message);
      onSaveState?.({
        status: "error",
        revision,
        message,
        retry: conflict ? () => setReload((value) => value + 1) : () => void run(mutate),
      });
    } finally {
      setBusy(false);
    }
  }

  const act = (object: SceneObject, action: ObjectAction, extra?: ActionExtra) =>
    run((revision) => applyObjectAction(jobId, object.id, action, revision, extra));

  if (missing) {
    return <Notice className="m-4">Chưa có vật thể: bước tách vật thể chạy sau khi dựng collision xong.</Notice>;
  }
  if (!scene) {
    return error ? (
      <Notice tone="rust" className="m-4">
        {error}
      </Notice>
    ) : (
      <p className="flex items-center gap-2 p-6 text-sm text-ink-muted" role="status">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tải vật thể…
      </p>
    );
  }
  const current = scene.objects.find((object) => object.id === selected) ?? null;
  const previous = typeof scene.provenance.edited_from === "string" ? scene.provenance.edited_from : null;
  return (
    <div className="relative size-full overflow-hidden bg-viewport">
      {/* Viewport 3D chiếm toàn bộ không gian khung nhìn */}
      <div className="size-full">
        {scene.environment.visual_ref ? (
          <MetricSceneView
            jobId={jobId}
            visual={scene.environment.visual_ref}
            collision={scene.environment.geometry_ref}
            cameras={cameras}
            boxes={boxes}
            objects={splats}
            gizmo={tool !== "none" && current && isPlaced(current) ? { id: current.id, mode: tool } : null}
            onTransform={(id, position, rotation) => run((revision) => setObjectTransform(jobId, revision, id, position, rotation))}
            focus={focus}
            onPickBox={selectFromScene}
            physicsObjects={physicsObjects}
            placement={
              placing
                ? {
                    label: placing.label,
                    dimensions: placing.dimensions,
                    onPlace: (point) => {
                      placing.commit(point);
                      setPlacing(null);
                    },
                    onCancel: cancelPlacing,
                  }
                : null
            }
            selectMode={selectMode}
            onToggleSelectMode={() => setSelectMode((previous) => !previous)}
            selectedObject={
              current
                ? {
                    id: current.id,
                    name: current.name,
                    active: current.active,
                    canTransform: isPlaced(current),
                  }
                : null
            }
            tool={tool}
            onTool={setTool}
            onDuplicate={current && !isIgnored(current) ? () => void act(current, "duplicate") : undefined}
            onToggleActive={current ? () => act(current, "hide", { active: !current.active }) : undefined}
            onDelete={
              current
                ? () => {
                    if (window.confirm(`Xoá "${current.name}" khỏi scene?`)) {
                      void act(current, "delete");
                      setSelected(null);
                    }
                  }
                : undefined
            }
            onDeselect={() => {
              setSelected(null);
              setTool("none");
            }}
          />
        ) : (
          <CollisionMeshCanvas url={jobArtifactContentUrl(jobId, scene.environment.geometry_ref)}>
            {visibleObjects.map((object) => (
              <ObjectBox key={object.id} object={object} selected={object.id === selected} onSelect={() => setSelected(object.id)} />
            ))}
          </CollisionMeshCanvas>
        )}
      </div>

      {/* Panel trái trong suốt: Khung vật thể trong scene */}
      <aside
        aria-label="Danh sách vật thể"
        className={cn(
          "absolute top-3 left-3 z-20 flex flex-col pointer-events-auto transition-all duration-200",
          leftCollapsed
            ? "w-auto"
            : "w-72 md:w-80 max-w-[calc(100vw-1.5rem)] max-h-[calc(100%-4.5rem)] rounded-lg border border-line-dark bg-viewport-deep/90 shadow-2xl backdrop-blur-md overflow-hidden text-on-dark",
        )}
      >
        {leftCollapsed ? (
          <button
            type="button"
            onClick={() => setLeftCollapsed(false)}
            className="flex items-center gap-2 rounded-lg border border-line-dark bg-viewport-deep/85 px-3 py-2 text-xs font-medium text-on-dark shadow-xl backdrop-blur-md hover:bg-viewport-deep transition-all"
            title="Xổ xuống danh sách vật thể trong scene"
            aria-label="Mở danh sách vật thể"
          >
            <Boxes className="size-4 text-ember-strong" aria-hidden />
            <span>Vật thể trong scene</span>
            <span className="rounded bg-on-dark/15 px-1.5 py-0.5 font-mono text-[11px] text-on-dark/90">
              {scene.objects.length}
            </span>
            <ChevronDown className="size-3.5 text-on-dark/70" aria-hidden />
          </button>
        ) : (
          <>
            <div className="space-y-2 border-b border-line-dark px-3 py-2.5 bg-viewport-deep/50">
              <div className="flex items-center justify-between gap-2">
                <h2 className="label-tech text-on-dark/70">Vật thể trong scene</h2>
                <div className="flex items-center gap-1">
                  {previous && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      title={`Hoàn tác: quay về ${previous} (ghi thành revision mới)`}
                      aria-label="Hoàn tác"
                      onClick={() => run((revision) => restoreSceneRevision(jobId, revision, previous))}
                      className="size-7 p-0 text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10"
                    >
                      <Undo2 className="size-3.5" aria-hidden />
                    </Button>
                  )}
                  <button
                    type="button"
                    onClick={() => setLeftCollapsed(true)}
                    className="rounded p-1 text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10 transition-colors"
                    title="Thu gọn danh sách vật thể"
                    aria-label="Thu gọn danh sách vật thể"
                  >
                    <ChevronUp className="size-4" aria-hidden />
                  </button>
                </div>
              </div>
              <p className="text-xs font-semibold text-on-dark">
                {scene.objects.length} vật thể · {counts.pending} chờ xác nhận
              </p>
              <div className="flex flex-wrap gap-1" role="group" aria-label="Lọc vật thể">
                {FILTERS.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    aria-pressed={filter === item.value}
                    onClick={() => setFilter(item.value)}
                    className={cn(
                      "rounded-md border px-2 py-0.5 text-xs transition-colors",
                      filter === item.value
                        ? "border-ember bg-ember-soft text-ember-strong font-medium"
                        : "border-line-dark text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10",
                    )}
                  >
                    {`${item.label} · ${counts[item.value]}`}
                  </button>
                ))}
              </div>
            </div>
            <ul className="min-h-0 flex-1 divide-y divide-line-dark overflow-y-auto">
              {visibleObjects.length === 0 && (
                <li className="px-3 py-6 text-center text-xs text-on-dark/60">
                  Không có vật nào trong nhóm này.
                </li>
              )}
              {visibleObjects.map((object) => (
                <li
                  key={object.id}
                  id={`object-${object.id}`}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 transition-colors",
                    object.id === selected ? "bg-ember-soft/30" : "hover:bg-on-dark/5",
                  )}
                >
                  <button
                    type="button"
                    aria-label={`Chọn ${object.name}`}
                    aria-pressed={object.id === selected}
                    onClick={() => flyTo(object.id)}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded py-1 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember"
                  >
                    <span className="size-2.5 shrink-0 rounded-sm" style={{ background: stateColor(object) }} aria-hidden />
                    <span className="truncate text-sm text-on-dark">{object.name}</span>
                  </button>
                  {object.state === "CANDIDATE" && !isIgnored(object) ? (
                    <span className="flex shrink-0 gap-1">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={busy}
                        aria-label={`Xác nhận ${object.name}`}
                        title="Xác nhận"
                        onClick={() => act(object, "confirm")}
                        className="size-7 p-0 border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep"
                      >
                        <Check className="size-3.5" aria-hidden />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        aria-label={`Loại ${object.name}`}
                        title="Loại"
                        onClick={() => act(object, "ignore")}
                        className="size-7 p-0 text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10"
                      >
                        <X className="size-3.5" aria-hidden />
                      </Button>
                    </span>
                  ) : (
                    <StateBadge object={object} />
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </aside>

      {/* Panel phải trong suốt: Chi tiết vật thể */}
      <aside
        aria-label="Inspector"
        className={cn(
          "absolute top-3 right-3 z-20 flex flex-col pointer-events-auto transition-all duration-200",
          rightCollapsed
            ? "w-auto"
            : "w-80 md:w-88 max-w-[calc(100vw-1.5rem)] max-h-[calc(100%-4.5rem)] rounded-lg border border-line-dark bg-viewport-deep/90 shadow-2xl backdrop-blur-md overflow-hidden text-on-dark",
        )}
      >
        {rightCollapsed ? (
          <button
            type="button"
            onClick={() => setRightCollapsed(false)}
            className="flex items-center gap-2 rounded-lg border border-line-dark bg-viewport-deep/85 px-3 py-2 text-xs font-medium text-on-dark shadow-xl backdrop-blur-md hover:bg-viewport-deep transition-all"
            title="Xổ xuống chi tiết vật thể"
            aria-label="Mở chi tiết vật thể"
          >
            <span className="size-2 rounded-full bg-ember" aria-hidden />
            <span>Chi tiết vật thể</span>
            {current && (
              <span className="max-w-28 truncate font-medium text-ember-strong">
                · {current.name}
              </span>
            )}
            <ChevronDown className="size-3.5 text-on-dark/70" aria-hidden />
          </button>
        ) : (
          <>
            <div className="flex items-center justify-between border-b border-line-dark px-3 py-2.5 bg-viewport-deep/50">
              <div className="flex items-center gap-1.5 min-w-0">
                <h2 className="label-tech text-on-dark/70">Chi tiết vật thể</h2>
                {current && (
                  <span className="truncate text-xs font-semibold text-on-dark">
                    · {current.name}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setRightCollapsed(true)}
                className="rounded p-1 text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10 transition-colors"
                title="Thu gọn chi tiết vật thể"
                aria-label="Thu gọn chi tiết vật thể"
              >
                <ChevronUp className="size-4" aria-hidden />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <ObjectifyNotice jobId={jobId} revision={scene.scene_revision} onRevision={() => setReload((value) => value + 1)} />
              {error && (
                <Notice tone="rust" className="m-3">
                  {error}
                </Notice>
              )}
              {current ? (
                <Inspector
                  key={current.id}
                  object={current}
                  busy={busy}
                  catalog={catalog}
                  onAct={(action, extra) => act(current, action, extra)}
                  onFlyTo={() => flyTo(current.id)}
                  onClose={() => setSelected(null)}
                />
              ) : (
                <div className="space-y-2 px-4 py-4 text-xs text-on-dark/70">
                  <p className="text-sm font-medium text-on-dark">Chọn một vật</p>
                  <p>Bấm hộp trong 3D hoặc một dòng trong danh sách để xem chi tiết và thao tác.</p>
                  <Legend />
                </div>
              )}
              {catalog && (
                <CatalogForm
                  catalog={catalog}
                  busy={busy}
                  onAdd={(family, position) => run((revision) => addCatalogObject(jobId, revision, family, position))}
                  onStartPlace={(family, dimensions) => {
                    const entry = catalog.entries.find((item) => item.family === family);
                    setPlacing({
                      label: entry?.semantic_class ? `${entry.semantic_class} (${family.replace(/^SM_/, "")})` : family,
                      dimensions,
                      commit: (point) => run((revision) => addCatalogObject(jobId, revision, family, [point[0], point[1], 0])),
                    });
                  }}
                />
              )}
              <AddObstacleForm
                busy={busy}
                onAdd={(name, dimensions, center) => run((revision) => addBoxObstacle(jobId, revision, name, dimensions, center))}
                onStartPlace={(name, dimensions) => {
                  setPlacing({
                    label: name,
                    dimensions,
                    commit: (point) =>
                      run((revision) =>
                        addBoxObstacle(jobId, revision, name, dimensions, [point[0], point[1], dimensions[2] / 2]),
                      ),
                  });
                }}
              />
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

function Legend() {
  const items = [
    ["var(--studio-ochre)", "Ứng viên"],
    ["var(--studio-sage)", "Đã xác nhận"],
    ["var(--studio-ink-subtle)", "Đã loại / đang ẩn"],
    ["var(--studio-ember)", "Đang chọn"],
  ] as const;
  return (
    <ul className="grid grid-cols-2 gap-1 pt-1 text-xs text-on-dark/70">
      {items.map(([color, label]) => (
        <li key={label} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: color }} aria-hidden />
          {label}
        </li>
      ))}
    </ul>
  );
}

/** Chi tiết + thao tác của vật đang chọn. Đổi tên cũng là một revision (Q5). */
function Inspector({
  object,
  busy,
  catalog,
  onAct,
  onFlyTo,
  onClose,
}: {
  object: SceneObject;
  busy: boolean;
  catalog: SceneCatalog | null;
  onAct: (action: ObjectAction, extra?: ActionExtra) => void;
  onFlyTo: () => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(object.name);
  const [label, setLabel] = useState(object.semantic_class ?? "");
  const [mass, setMass] = useState(object.physics?.mass_source === "user" ? String(object.physics.mass_kg ?? "") : "");
  // Người dùng chọn thẳng một asset trong danh mục Isaac; nhãn lưu vào scene là lớp của asset đó.
  const assets = catalog ? catalog.entries.filter((item) => item.semantic_class) : [];
  const savedFamily = object.physics?.provenance?.asset_family;
  const [family, setFamily] = useState(typeof savedFamily === "string" ? savedFamily : "");
  const chosen = assets.find((item) => item.family === family) ?? assets.find((item) => item.semantic_class === label);
  const removed = isIgnored(object);
  const massValue = mass.trim() === "" ? null : Number(mass);
  const massValid = massValue === null || (Number.isFinite(massValue) && massValue > 0);
  const [x, y, z] = object.transform.translation_xyz;
  const size = object.primitive_dimensions_xyz_m;
  const rename = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed && trimmed !== object.name) onAct("rename", { name: trimmed });
  };
  return (
    <div className="space-y-4 border-b border-line-dark px-4 py-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-on-dark">{object.name}</p>
          <p className="font-mono text-xs text-on-dark/60">{object.id}</p>
        </div>
        <button type="button" onClick={onClose} className="rounded p-1 text-on-dark/60 hover:text-on-dark hover:bg-on-dark/10 transition-colors" aria-label="Bỏ chọn">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StateBadge object={object} />
        <Badge tone="neutral">{object.origin === "reconstructed" ? "Tách từ scene" : "Người dùng thêm"}</Badge>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-on-dark/60">Tâm (m)</dt>
        <dd className="font-mono text-on-dark">
          {x.toFixed(2)}, {y.toFixed(2)}, {z.toFixed(2)}
        </dd>
        {size && (
          <>
            <dt className="text-on-dark/60">Kích thước (m)</dt>
            <dd className="font-mono text-on-dark">{size.map((value) => value.toFixed(2)).join(" × ")}</dd>
          </>
        )}
      </dl>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="secondary" onClick={onFlyTo} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
          <Crosshair aria-hidden /> Bay tới
        </Button>
        {object.state === "CANDIDATE" && !isIgnored(object) && (
          <>
            <Button size="sm" disabled={busy} onClick={() => onAct("confirm")}>
              <Check aria-hidden /> Xác nhận
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAct("ignore")} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
              <X aria-hidden /> Loại
            </Button>
          </>
        )}
        {removed && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAct("restore")} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
            <Undo2 aria-hidden /> Khôi phục
          </Button>
        )}
      </div>
      {catalog && !removed && (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (massValid) onAct("label", { semantic_class: label || null, mass_kg: label ? massValue : null, asset_family: label ? (chosen?.family ?? null) : null });
          }}
        >
          <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
            <span className="flex items-center gap-1">
              <Tag className="size-3.5" aria-hidden /> Nhãn — chọn asset tương ứng trong thư viện Isaac
            </span>
            <select
              className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none"
              value={chosen?.family ?? ""}
              onChange={(event) => {
                const entry = assets.find((item) => item.family === event.target.value);
                setFamily(entry?.family ?? "");
                setLabel(entry?.semantic_class ?? "");
              }}
            >
              <option value="" className="bg-viewport-deep text-on-dark">Chưa gán</option>
              {catalog.classes.map((name) => (
                <optgroup key={name} label={name} className="bg-viewport-deep text-on-dark">
                  {assets
                    .filter((item) => item.semantic_class === name)
                    .map((item) => (
                      <option key={item.family} value={item.family} className="bg-viewport-deep text-on-dark">
                        {item.family.replace(/^SM_/, "")} · {item.size_xyz_m.map((value) => value.toFixed(2)).join("×")} m
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          {chosen && (
            <p className="text-xs text-on-dark/70">
              Nhãn <span className="font-medium text-on-dark">{chosen.semantic_class}</span> ·{" "}
              {chosen.dynamic
                ? `khối lượng mặc định ${chosen.default_mass_kg === null ? "theo mật độ × thể tích" : `${chosen.default_mass_kg} kg`}`
                : "vật cố định (collider tĩnh)"}
            </p>
          )}
          <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
            Khối lượng (kg) — bỏ trống để dùng mặc định của nhãn
            <input
              className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none"
              inputMode="decimal"
              value={mass}
              disabled={!label}
              aria-invalid={!massValid}
              onChange={(event) => setMass(event.target.value)}
            />
          </label>
          {object.physics && (
            <p className="text-xs text-on-dark/70">
              {object.physics.dynamic
                ? `Hiện tại: ${object.physics.mass_kg?.toLocaleString("vi-VN", { maximumFractionDigits: 2 })} kg (${MASS_SOURCE[object.physics.mass_source ?? "user"]}) · ma sát ${object.physics.static_friction}`
                : "Vật cố định: chỉ có collider tĩnh, không có khối lượng."}
            </p>
          )}
          <Button size="sm" variant="secondary" type="submit" disabled={busy || !massValid} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
            Lưu nhãn
          </Button>
        </form>
      )}
      <form className="flex items-end gap-2" onSubmit={rename}>
        <label className="flex min-w-0 flex-1 flex-col gap-0.5 text-xs text-on-dark/70">
          Tên
          <input
            className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <Button size="sm" variant="secondary" type="submit" disabled={busy || !name.trim() || name.trim() === object.name} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
          <Pencil aria-hidden /> Đổi tên
        </Button>
      </form>
    </div>
  );
}

type ActionExtra = { active?: boolean; name?: string; semantic_class?: string | null; mass_kg?: number | null; asset_family?: string | null };

const MASS_SOURCE: Record<string, string> = {
  catalog_default: "mặc định của nhãn",
  catalog_density: "mật độ giả định × thể tích",
  user: "bạn nhập",
  asset: "theo asset",
};

/** Vật đang có mặt trong scene: ứng viên chờ xác nhận hoặc vật đã xác nhận đang hiện. */
function isPlaced(object: SceneObject): boolean {
  if (isIgnored(object)) return false;
  return object.state === "CANDIDATE" || object.active;
}

/** Thêm vật từ thư viện asset Isaac: chọn họ asset + vị trí trên sàn. */
function CatalogForm({
  catalog,
  busy,
  onAdd,
  onStartPlace,
}: {
  catalog: SceneCatalog;
  busy: boolean;
  onAdd: (family: string, position: [number, number, number]) => void;
  onStartPlace?: (family: string, dimensions: [number, number, number]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [family, setFamily] = useState(catalog.entries[0]?.family ?? "");
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  if (!open) {
    return (
      <div className="border-t border-line-dark p-3">
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
          <Library aria-hidden /> Thêm từ thư viện
        </Button>
      </div>
    );
  }
  const entry = catalog.entries.find((item) => item.family === family);
  const valid = Boolean(entry) && Number.isFinite(Number(x)) && Number.isFinite(Number(y));
  return (
    <form
      className="space-y-2 border-t border-line-dark p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        onAdd(family, [Number(x), Number(y), 0]);
        setOpen(false);
      }}
    >
      <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
        Asset Isaac
        <select className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none" value={family} onChange={(event) => setFamily(event.target.value)}>
          {catalog.entries.map((item) => (
            <option key={item.family} value={item.family} className="bg-viewport-deep text-on-dark">
              {item.semantic_class} · {item.family.replace(/^SM_/, "")}
            </option>
          ))}
        </select>
      </label>
      {entry && (
        <p className="text-xs text-on-dark/70">
          {entry.size_xyz_m.map((value) => value.toFixed(2)).join(" × ")} m ·{" "}
          {entry.dynamic ? (entry.default_mass_kg ? `${entry.default_mass_kg} kg (mặc định)` : "khối lượng theo mật độ giả định") : "vật cố định"}. Trên
          web vật hiện bằng hộp; trong Isaac là asset thật.
        </p>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
          Vị trí X (m)
          <input className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none" inputMode="decimal" value={x} onChange={(event) => setX(event.target.value)} />
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
          Vị trí Y (m)
          <input className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none" inputMode="decimal" value={y} onChange={(event) => setY(event.target.value)} />
        </label>
      </div>
      <p className="text-xs text-on-dark/50">{catalog.physics_note}</p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" type="submit" disabled={busy || !valid}>
          Thêm
        </Button>
        {onStartPlace && entry && (
          <Button
            size="sm"
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              onStartPlace(family, entry.size_xyz_m);
              setOpen(false);
            }}
            className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep"
            title="Di chuột vào scene để đặt vị trí"
          >
            <Crosshair className="size-3.5" aria-hidden /> Đặt bằng chuột
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)} className="text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10">
          Huỷ
        </Button>
      </div>
    </form>
  );
}

/**
 * Màu khung vật lấy từ bảng màu đang chọn (cùng vai trò với badge trạng thái): ember = đang chọn, ochre = ứng viên,
 * sage = đã xác nhận, ink-subtle = đã loại/ẩn. Lớp phủ 3D cần mã màu cụ thể nên đọc giá trị biến lúc vẽ; component
 * gọi `useSyncExternalStore(subscribeTheme, themeKey)` để vẽ lại khi đổi theme.
 */
function selectedColor(): string {
  return themeColor("--studio-ember", "#e8743b");
}

function stateColor(object: SceneObject): string {
  if (isIgnored(object) || !object.active && object.state === "CONFIRMED") return themeColor("--studio-ink-subtle", "#8a7e70");
  return object.state === "CONFIRMED" ? themeColor("--studio-sage", "#5e8c61") : themeColor("--studio-ochre", "#b7862a");
}

function isIgnored(object: SceneObject): boolean {
  return object.provenance.review === "IGNORED" || object.provenance.review === "DELETED";
}

function StateBadge({ object }: { object: SceneObject }) {
  if (object.provenance.review === "DELETED") return <Badge>Đã xoá</Badge>;
  if (isIgnored(object)) return <Badge>Đã loại</Badge>;
  if (object.state === "CANDIDATE") return <Badge tone="ochre">Ứng viên</Badge>;
  return object.active ? <Badge tone="sage">Đã xác nhận</Badge> : <Badge>Đang ẩn</Badge>;
}

/** Hộp khung dây trong khung Z-up của collision mesh; màu theo trạng thái review. */
function ObjectBox({ object, selected, onSelect }: { object: SceneObject; selected: boolean; onSelect: () => void }) {
  const dimensions = object.primitive_dimensions_xyz_m;
  if (!dimensions) return null;
  const color = selected ? selectedColor() : stateColor(object);
  return (
    <mesh
      position={object.transform.translation_xyz}
      quaternion={object.transform.rotation_quaternion_xyzw}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
    >
      <boxGeometry args={dimensions} />
      <meshBasicMaterial color={color} wireframe />
    </mesh>
  );
}

function AddObstacleForm({
  busy,
  onAdd,
  onStartPlace,
}: {
  busy: boolean;
  onAdd: (name: string, dimensions: [number, number, number], center: [number, number, number]) => void;
  onStartPlace?: (name: string, dimensions: [number, number, number]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState({ name: "", x: "0", y: "0", sx: "0.6", sy: "0.4", sz: "0.5" });
  const field = (key: keyof typeof values, label: string) => (
    <label className="flex flex-col gap-0.5 text-xs text-on-dark/70">
      {label}
      <input
        className="h-8 rounded-md border border-line-dark bg-viewport-deep/70 px-2 text-sm text-on-dark focus:border-ember focus:outline-none"
        inputMode={key === "name" ? "text" : "decimal"}
        value={values[key]}
        onChange={(event) => setValues({ ...values, [key]: event.target.value })}
      />
    </label>
  );
  if (!open) {
    return (
      <div className="border-t border-line-dark p-3">
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)} className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep">
          <Plus aria-hidden /> Thêm vật cản hộp
        </Button>
      </div>
    );
  }
  const numbers = [values.x, values.y, values.sx, values.sy, values.sz].map(Number);
  const valid = numbers.every(Number.isFinite) && numbers.slice(2).every((value) => value > 0);
  const validDims = [values.sx, values.sy, values.sz].map(Number).every((v) => Number.isFinite(v) && v > 0);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    const [x, y, sx, sy, sz] = numbers;
    // Vật cản đặt trên sàn: tâm hộp cao bằng nửa chiều cao.
    onAdd(values.name, [sx, sy, sz], [x, y, sz / 2]);
    setOpen(false);
  }
  return (
    <form className="space-y-2 border-t border-line-dark p-3" onSubmit={submit}>
      {field("name", "Tên")}
      <div className="grid grid-cols-2 gap-2">
        {field("x", "Tâm X (m)")}
        {field("y", "Tâm Y (m)")}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {field("sx", "Dài (m)")}
        {field("sy", "Rộng (m)")}
        {field("sz", "Cao (m)")}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" type="submit" disabled={busy || !valid}>
          Thêm
        </Button>
        {onStartPlace && (
          <Button
            size="sm"
            type="button"
            variant="secondary"
            disabled={busy || !validDims}
            onClick={() => {
              const [, , sx, sy, sz] = numbers;
              onStartPlace(values.name.trim() || "Vật cản hộp", [sx, sy, sz]);
              setOpen(false);
            }}
            className="border-line-dark bg-viewport-deep/80 text-on-dark hover:bg-viewport-deep"
            title="Di chuột vào scene để đặt vị trí"
          >
            <Crosshair className="size-3.5" aria-hidden /> Đặt bằng chuột
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)} className="text-on-dark/70 hover:text-on-dark hover:bg-on-dark/10">
          Huỷ
        </Button>
      </div>
    </form>
  );
}
