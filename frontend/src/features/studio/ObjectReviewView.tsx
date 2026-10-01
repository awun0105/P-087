"use client";

import dynamic from "next/dynamic";
import { Check, Copy, Crosshair, Eye, EyeOff, Library, Loader2, Move3d, Pencil, Plus, RotateCw, Tag, Trash2, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import type { GizmoMode, OverlayBox, OverlayObject } from "@/features/viewer/scene-overlay";
import { ApiError } from "@/lib/api/client";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import {
  addBoxObstacle,
  addCatalogObject,
  applyObjectAction,
  getJobScene,
  getLabelSuggestions,
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

/** Trạng thái lưu SceneObject cho header scene (PRODUCT.md Q5: mỗi thao tác là một revision). */
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
 * Studio vật thể (ADR 0006, PRODUCT-07/07A, PRODUCT.md P5): danh sách · viewport 3DGS hệ mét ·
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
  const [catalog, setCatalog] = useState<SceneCatalog | null>(null);
  const stale = Boolean(revision && scene && !busy && revision !== scene.scene_revision);

  /** Chọn và cho camera bay tới vật (từ danh sách hoặc nút trong inspector). */
  const flyTo = (id: string) => {
    setSelected(id);
    setFocus((previous) => ({ id, nonce: (previous?.nonce ?? 0) + 1 }));
  };
  /** Chọn bằng cách bấm hộp trong 3D: đánh dấu và cuộn danh sách tới vật đó. */
  const selectFromScene = (id: string) => {
    setSelected(id);
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
      else setError(result.error.detail);
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

  // Scene theo vật (pipeline v2): mỗi vật có Gaussian riêng. Vật đã loại/xoá hoặc đang ẩn không vẽ.
  const splats = useMemo<OverlayObject[]>(
    () =>
      (scene?.objects ?? []).map((object) => ({
        id: object.id,
        url: object.visual_ref?.artifact_type === "ObjectGaussians" ? jobArtifactContentUrl(jobId, object.visual_ref) : null,
        position: object.transform.translation_xyz,
        rotation_xyzw: object.transform.rotation_quaternion_xyzw,
        visible: isPlaced(object),
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
  const boxes = useMemo<OverlayBox[]>(
    () =>
      visibleObjects
        .filter((object) => object.primitive_dimensions_xyz_m)
        .map((object) => ({
          id: object.id,
          center: object.transform.translation_xyz,
          rotation_xyzw: object.transform.rotation_quaternion_xyzw,
          dimensions: object.primitive_dimensions_xyz_m!,
          color: object.id === selected ? SELECTED_COLOR : stateColor(object),
          emphasized: object.id === selected,
        })),
    [visibleObjects, selected],
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
        : cause instanceof Error
          ? cause.message
          : "Thao tác thất bại";
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
  const method = String(scene.provenance.object_extraction ?? "không rõ");
  const previous = typeof scene.provenance.edited_from === "string" ? scene.provenance.edited_from : null;
  const inpainted = Number(scene.provenance.inpainted_gaussians ?? 0);
  return (
    <div className="grid size-full grid-rows-[minmax(50vh,1fr)_auto_auto] lg:grid-cols-[18rem_minmax(0,1fr)_20rem] lg:grid-rows-1">
      <aside className="order-2 flex max-h-[50vh] min-h-0 flex-col border-t border-line bg-paper-raised lg:order-1 lg:max-h-none lg:border-t-0 lg:border-r">
        <div className="space-y-2 border-b border-line px-3 py-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-ink">
              {scene.objects.length} vật thể · {counts.pending} chờ xác nhận
            </p>
            {previous && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                title={`Hoàn tác: quay về ${previous} (ghi thành revision mới)`}
                aria-label="Hoàn tác"
                onClick={() => run((revision) => restoreSceneRevision(jobId, revision, previous))}
              >
                <Undo2 aria-hidden />
              </Button>
            )}
          </div>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Lọc vật thể">
            {FILTERS.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={filter === item.value}
                onClick={() => setFilter(item.value)}
                className={cn(
                  "rounded-md border px-2 py-0.5 text-xs transition-colors",
                  filter === item.value ? "border-ember bg-ember-soft text-ember-strong" : "border-line text-ink-muted hover:text-ink",
                )}
              >
                {`${item.label} · ${counts[item.value]}`}
              </button>
            ))}
          </div>
        </div>
        <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
          {visibleObjects.length === 0 && <li className="px-3 py-6 text-center text-xs text-ink-muted">Không có vật nào trong nhóm này.</li>}
          {visibleObjects.map((object) => (
            <li
              key={object.id}
              id={`object-${object.id}`}
              className={cn("flex cursor-pointer items-center gap-2 px-3 py-2", object.id === selected && "bg-ember-soft/40")}
              onClick={() => flyTo(object.id)}
            >
              <span className="size-2.5 shrink-0 rounded-sm" style={{ background: stateColor(object) }} aria-hidden />
              <span className="min-w-0 flex-1 truncate text-sm text-ink">{object.name}</span>
              {object.state === "CANDIDATE" && !isIgnored(object) ? (
                <span className="flex shrink-0 gap-1" onClick={(event) => event.stopPropagation()}>
                  <Button size="sm" variant="secondary" disabled={busy} aria-label={`Xác nhận ${object.name}`} title="Xác nhận" onClick={() => act(object, "confirm")}>
                    <Check aria-hidden />
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy} aria-label={`Loại ${object.name}`} title="Loại" onClick={() => act(object, "ignore")}>
                    <X aria-hidden />
                  </Button>
                </span>
              ) : (
                <StateBadge object={object} />
              )}
            </li>
          ))}
        </ul>
      </aside>
      <div className="relative order-1 min-h-[50vh] bg-viewport lg:order-2">
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
          />
        ) : (
          // Scene không có visual 3DGS: chỉ còn collision mesh để định vị hộp.
          <CollisionMeshCanvas url={jobArtifactContentUrl(jobId, scene.environment.geometry_ref)}>
            {visibleObjects.map((object) => (
              <ObjectBox key={object.id} object={object} selected={object.id === selected} onSelect={() => setSelected(object.id)} />
            ))}
          </CollisionMeshCanvas>
        )}
      </div>
      <aside className="order-3 flex min-h-0 flex-col overflow-y-auto border-t border-line bg-paper-raised lg:border-t-0 lg:border-l" aria-label="Inspector">
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
            jobId={jobId}
            catalog={catalog}
            tool={tool}
            onTool={setTool}
            onAct={(action, extra) => act(current, action, extra)}
            onFlyTo={() => flyTo(current.id)}
            onClose={() => setSelected(null)}
          />
        ) : (
          <div className="space-y-2 px-4 py-4 text-xs text-ink-muted">
            <p className="text-sm font-medium text-ink">Chọn một vật</p>
            <p>Bấm hộp trong 3D hoặc một dòng trong danh sách để xem chi tiết và thao tác.</p>
            <p>
              Tách bằng <code>{method}</code>. Ứng viên là gợi ý; chỉ vật đã xác nhận và đang hiện mới đi vào gói mô phỏng.
            </p>
            {inpainted > 0 && (
              <p>
                Nền đã được vá {inpainted.toLocaleString("vi-VN")} Gaussian ở chỗ vật từng che — đó là hình suy đoán, chưa
                từng được quay.
              </p>
            )}
            <Legend />
          </div>
        )}
        {catalog && (
          <CatalogForm
            catalog={catalog}
            busy={busy}
            onAdd={(family, position) => run((revision) => addCatalogObject(jobId, revision, family, position))}
          />
        )}
        <AddObstacleForm
          busy={busy}
          onAdd={(name, dimensions, center) => run((revision) => addBoxObstacle(jobId, revision, name, dimensions, center))}
        />
      </aside>
    </div>
  );
}

function Legend() {
  const items = [
    ["#facc15", "Ứng viên"],
    ["#22c55e", "Đã xác nhận"],
    ["#9ca3af", "Đã loại / đang ẩn"],
    [SELECTED_COLOR, "Đang chọn"],
  ] as const;
  return (
    <ul className="grid grid-cols-2 gap-1 pt-1">
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
  jobId,
  catalog,
  tool,
  onTool,
  onAct,
  onFlyTo,
  onClose,
}: {
  object: SceneObject;
  busy: boolean;
  jobId: string;
  catalog: SceneCatalog | null;
  tool: GizmoMode | "none";
  onTool: (tool: GizmoMode | "none") => void;
  onAct: (action: ObjectAction, extra?: ActionExtra) => void;
  onFlyTo: () => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(object.name);
  const [label, setLabel] = useState(object.semantic_class ?? "");
  const [mass, setMass] = useState(object.physics?.mass_source === "user" ? String(object.physics.mass_kg ?? "") : "");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    getLabelSuggestions(jobId, object.id, controller.signal).then(
      (result) => setSuggestions(result.suggestions),
      () => setSuggestions([]),
    );
    return () => controller.abort();
  }, [jobId, object.id]);
  const placed = isPlaced(object);
  const removed = isIgnored(object);
  const massValue = mass.trim() === "" ? null : Number(mass);
  const massValid = massValue === null || (Number.isFinite(massValue) && massValue > 0);
  const classes = catalog ? [...suggestions, ...catalog.classes.filter((item) => !suggestions.includes(item))] : [];
  const [x, y, z] = object.transform.translation_xyz;
  const size = object.primitive_dimensions_xyz_m;
  const rename = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed && trimmed !== object.name) onAct("rename", { name: trimmed });
  };
  return (
    <div className="space-y-4 border-b border-line px-4 py-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{object.name}</p>
          <p className="font-mono text-xs text-ink-subtle">{object.id}</p>
        </div>
        <button type="button" onClick={onClose} className="rounded p-1 text-ink-muted hover:text-ink" aria-label="Bỏ chọn">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StateBadge object={object} />
        <Badge tone="neutral">{object.origin === "reconstructed" ? "Tách từ scene" : "Người dùng thêm"}</Badge>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-ink-muted">Tâm (m)</dt>
        <dd className="font-mono text-ink">
          {x.toFixed(2)}, {y.toFixed(2)}, {z.toFixed(2)}
        </dd>
        {size && (
          <>
            <dt className="text-ink-muted">Kích thước (m)</dt>
            <dd className="font-mono text-ink">{size.map((value) => value.toFixed(2)).join(" × ")}</dd>
          </>
        )}
      </dl>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="secondary" onClick={onFlyTo}>
          <Crosshair aria-hidden /> Bay tới
        </Button>
        {object.state === "CANDIDATE" && !isIgnored(object) && (
          <>
            <Button size="sm" disabled={busy} onClick={() => onAct("confirm")}>
              <Check aria-hidden /> Xác nhận
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAct("ignore")}>
              <X aria-hidden /> Loại
            </Button>
          </>
        )}
        {object.state === "CONFIRMED" && !removed && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAct("hide", { active: !object.active })}>
            {object.active ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
            {object.active ? "Ẩn khỏi mô phỏng" : "Đưa lại vào mô phỏng"}
          </Button>
        )}
        {removed ? (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onAct("restore")}>
            <Undo2 aria-hidden /> Khôi phục
          </Button>
        ) : (
          <>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAct("duplicate")}>
              <Copy aria-hidden /> Nhân bản
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={() => {
                if (window.confirm(`Xoá "${object.name}" khỏi scene? Hình và collider của vật không còn trong scene và gói mô phỏng.`)) onAct("delete");
              }}
            >
              <Trash2 aria-hidden /> Xoá
            </Button>
          </>
        )}
      </div>
      {placed && (
        <div className="space-y-1.5">
          <p className="text-xs text-ink-muted">Di chuyển trong 3D (thả chuột là lưu thành revision mới)</p>
          <div className="flex gap-1.5" role="group" aria-label="Công cụ biến đổi">
            <Button size="sm" variant={tool === "translate" ? "primary" : "secondary"} aria-pressed={tool === "translate"} onClick={() => onTool(tool === "translate" ? "none" : "translate")}>
              <Move3d aria-hidden /> Dịch
            </Button>
            <Button size="sm" variant={tool === "rotate" ? "primary" : "secondary"} aria-pressed={tool === "rotate"} onClick={() => onTool(tool === "rotate" ? "none" : "rotate")}>
              <RotateCw aria-hidden /> Xoay
            </Button>
          </div>
        </div>
      )}
      {catalog && !removed && (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (massValid) onAct("label", { semantic_class: label || null, mass_kg: label ? massValue : null });
          }}
        >
          <label className="flex flex-col gap-0.5 text-xs text-ink-muted">
            <span className="flex items-center gap-1">
              <Tag className="size-3.5" aria-hidden /> Nhãn {suggestions.length > 0 && <span className="text-ink-subtle">(gợi ý theo kích thước xếp trước)</span>}
            </span>
            <select className="h-8 rounded-md border border-line-strong bg-paper px-2 text-sm text-ink" value={label} onChange={(event) => setLabel(event.target.value)}>
              <option value="">Chưa gán</option>
              {classes.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-xs text-ink-muted">
            Khối lượng (kg) — bỏ trống để dùng mặc định của nhãn
            <input
              className="h-8 rounded-md border border-line-strong bg-paper px-2 text-sm text-ink"
              inputMode="decimal"
              value={mass}
              disabled={!label}
              aria-invalid={!massValid}
              onChange={(event) => setMass(event.target.value)}
            />
          </label>
          {object.physics && (
            <p className="text-xs text-ink-muted">
              {object.physics.dynamic
                ? `Hiện tại: ${object.physics.mass_kg?.toLocaleString("vi-VN", { maximumFractionDigits: 2 })} kg (${MASS_SOURCE[object.physics.mass_source ?? "user"]}) · ma sát ${object.physics.static_friction}`
                : "Vật cố định: chỉ có collider tĩnh, không có khối lượng."}
            </p>
          )}
          <Button size="sm" variant="secondary" type="submit" disabled={busy || !massValid}>
            Lưu nhãn
          </Button>
        </form>
      )}
      <form className="flex items-end gap-2" onSubmit={rename}>
        <label className="flex min-w-0 flex-1 flex-col gap-0.5 text-xs text-ink-muted">
          Tên
          <input
            className="h-8 rounded-md border border-line-strong bg-paper px-2 text-sm text-ink"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <Button size="sm" variant="secondary" type="submit" disabled={busy || !name.trim() || name.trim() === object.name}>
          <Pencil aria-hidden /> Đổi tên
        </Button>
      </form>
    </div>
  );
}

type ActionExtra = { active?: boolean; name?: string; semantic_class?: string | null; mass_kg?: number | null };

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
}: {
  catalog: SceneCatalog;
  busy: boolean;
  onAdd: (family: string, position: [number, number, number]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [family, setFamily] = useState(catalog.entries[0]?.family ?? "");
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  if (!open) {
    return (
      <div className="border-t border-line p-3">
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
          <Library aria-hidden /> Thêm từ thư viện
        </Button>
      </div>
    );
  }
  const entry = catalog.entries.find((item) => item.family === family);
  const valid = Boolean(entry) && Number.isFinite(Number(x)) && Number.isFinite(Number(y));
  return (
    <form
      className="space-y-2 border-t border-line p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        onAdd(family, [Number(x), Number(y), 0]);
        setOpen(false);
      }}
    >
      <label className="flex flex-col gap-0.5 text-xs text-ink-muted">
        Asset Isaac
        <select className="h-8 rounded-md border border-line-strong bg-paper px-2 text-sm text-ink" value={family} onChange={(event) => setFamily(event.target.value)}>
          {catalog.entries.map((item) => (
            <option key={item.family} value={item.family}>
              {item.semantic_class} · {item.family.replace(/^SM_/, "")}
            </option>
          ))}
        </select>
      </label>
      {entry && (
        <p className="text-xs text-ink-muted">
          {entry.size_xyz_m.map((value) => value.toFixed(2)).join(" × ")} m ·{" "}
          {entry.dynamic ? (entry.default_mass_kg ? `${entry.default_mass_kg} kg (mặc định)` : "khối lượng theo mật độ giả định") : "vật cố định"}. Trên
          web vật hiện bằng hộp; trong Isaac là asset thật.
        </p>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-ink-muted">
          Vị trí X (m)
          <input className="h-8 rounded-md border border-line-strong bg-paper px-2 text-sm text-ink" inputMode="decimal" value={x} onChange={(event) => setX(event.target.value)} />
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-ink-muted">
          Vị trí Y (m)
          <input className="h-8 rounded-md border border-line-strong bg-paper px-2 text-sm text-ink" inputMode="decimal" value={y} onChange={(event) => setY(event.target.value)} />
        </label>
      </div>
      <p className="text-xs text-ink-subtle">{catalog.physics_note}</p>
      <div className="flex gap-2">
        <Button size="sm" type="submit" disabled={busy || !valid}>
          Thêm
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Huỷ
        </Button>
      </div>
    </form>
  );
}

const SELECTED_COLOR = "#f97316";

/** Màu hộp theo trạng thái review: vàng = ứng viên, xanh lá = đã xác nhận, xám = đã loại/ẩn. */
function stateColor(object: SceneObject): string {
  if (isIgnored(object) || !object.active && object.state === "CONFIRMED") return "#9ca3af";
  return object.state === "CONFIRMED" ? "#22c55e" : "#facc15";
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
  const color = selected ? SELECTED_COLOR : stateColor(object);
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
}: {
  busy: boolean;
  onAdd: (name: string, dimensions: [number, number, number], center: [number, number, number]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState({ name: "", x: "0", y: "0", sx: "0.6", sy: "0.4", sz: "0.5" });
  const field = (key: keyof typeof values, label: string) => (
    <label className="flex flex-col gap-0.5 text-xs text-ink-muted">
      {label}
      <input
        className="h-8 rounded-md border border-line-strong bg-paper px-2 text-sm text-ink"
        inputMode={key === "name" ? "text" : "decimal"}
        value={values[key]}
        onChange={(event) => setValues({ ...values, [key]: event.target.value })}
      />
    </label>
  );
  if (!open) {
    return (
      <div className="border-t border-line p-3">
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
          <Plus aria-hidden /> Thêm vật cản hộp
        </Button>
      </div>
    );
  }
  const numbers = [values.x, values.y, values.sx, values.sy, values.sz].map(Number);
  const valid = numbers.every(Number.isFinite) && numbers.slice(2).every((value) => value > 0);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    const [x, y, sx, sy, sz] = numbers;
    // Vật cản đặt trên sàn: tâm hộp cao bằng nửa chiều cao.
    onAdd(values.name, [sx, sy, sz], [x, y, sz / 2]);
    setOpen(false);
  }
  return (
    <form className="space-y-2 border-t border-line p-3" onSubmit={submit}>
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
      <div className="flex gap-2">
        <Button size="sm" type="submit" disabled={busy || !valid}>
          Thêm
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Huỷ
        </Button>
      </div>
    </form>
  );
}
