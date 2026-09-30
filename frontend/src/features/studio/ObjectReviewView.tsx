"use client";

import { Check, Eye, EyeOff, Loader2, Plus, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import { MetricSceneView } from "@/features/studio/MetricSceneView";
import { SimulationPackagePanel } from "@/features/studio/SimulationPackagePanel";
import { CollisionMeshCanvas } from "@/features/studio/StageViewer";
import type { OverlayBox } from "@/features/viewer/scene-overlay";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import {
  addBoxObstacle,
  applyObjectAction,
  getJobScene,
  getStageViews,
  type ObjectAction,
} from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { SceneIR, SceneObject } from "@/lib/contracts/api";
import type { StageView } from "@/lib/contracts/studio";

/**
 * Xác nhận vật thể ứng viên (ADR 0006, PRODUCT-07/07A): hộp ứng viên vẽ trên collision mesh,
 * người dùng xác nhận/loại từng vật hoặc thêm vật cản hộp. Mỗi thao tác là một revision SceneIR
 * mới ở backend; màn hình chỉ giữ revision vừa nhận, không tự sửa scene ở client.
 */
export function ObjectReviewView({ jobId }: { jobId: string }) {
  const [scene, setScene] = useState<SceneIR | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [showIgnored, setShowIgnored] = useState(false);
  const [cameras, setCameras] = useState<StageView["cameras"]>([]);
  const [focus, setFocus] = useState<{ id: string; nonce: number } | undefined>();
  const [reload, setReload] = useState(0);

  /** Chọn từ danh sách: đánh dấu và cho camera bay tới vật. */
  const selectFromList = (object: SceneObject) => {
    setSelected(object.id);
    setFocus((previous) => ({ id: object.id, nonce: (previous?.nonce ?? 0) + 1 }));
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
      if (result.ok) setScene(result.data.scene);
      else if (result.error.status === 404) setMissing(true);
      else setError(result.error.detail);
    });
    return () => controller.abort();
  }, [jobId, reload]);

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

  const visibleObjects = useMemo(
    () => scene?.objects.filter((object) => showIgnored || !isIgnored(object)) ?? [],
    [scene, showIgnored],
  );
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
    setBusy(true);
    setError(null);
    try {
      setScene((await mutate(scene.scene_revision)).scene);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Thao tác thất bại");
    } finally {
      setBusy(false);
    }
  }

  const act = (object: SceneObject, action: ObjectAction, extra?: { active?: boolean }) =>
    run((revision) => applyObjectAction(jobId, object.id, action, revision, extra));

  if (missing) {
    return <Notice>Chưa có vật thể: bước tách vật thể chạy sau khi dựng collision xong.</Notice>;
  }
  if (!scene) {
    return error ? (
      <Notice tone="rust">{error}</Notice>
    ) : (
      <p className="flex items-center gap-2 p-6 text-sm text-ink-muted" role="status">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tải vật thể…
      </p>
    );
  }
  const visible = visibleObjects;
  const pending = scene.objects.filter((object) => object.state === "CANDIDATE" && !isIgnored(object)).length;
  const method = String(scene.provenance.object_extraction ?? "không rõ");
  return (
    <div className="flex size-full flex-col lg:flex-row">
      <div className="relative min-h-[50vh] flex-1 bg-viewport">
        {scene.environment.visual_ref ? (
          <MetricSceneView
            jobId={jobId}
            visual={scene.environment.visual_ref}
            collision={scene.environment.geometry_ref}
            cameras={cameras}
            boxes={boxes}
            focus={focus}
            onPickBox={selectFromScene}
          />
        ) : (
          // Scene không có visual 3DGS: chỉ còn collision mesh để định vị hộp.
          <CollisionMeshCanvas url={jobArtifactContentUrl(jobId, scene.environment.geometry_ref)}>
            {visible.map((object) => (
              <ObjectBox
                key={object.id}
                object={object}
                selected={object.id === selected}
                onSelect={() => setSelected(object.id)}
              />
            ))}
          </CollisionMeshCanvas>
        )}
      </div>
      <aside className="flex max-h-[50vh] w-full flex-col border-t border-line bg-paper-raised lg:max-h-none lg:w-96 lg:border-t-0 lg:border-l">
        <div className="space-y-1 border-b border-line px-4 py-3">
          <p className="text-sm font-semibold text-ink">
            {scene.objects.length} vật thể · {pending} chờ xác nhận
          </p>
          <p className="text-xs text-ink-muted">
            Tách bằng <code>{method}</code> · revision {scene.scene_revision}. Ứng viên là gợi ý, chỉ vật đã xác nhận
            đi vào gói mô phỏng.
          </p>
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            <input type="checkbox" checked={showIgnored} onChange={(event) => setShowIgnored(event.target.checked)} />
            Hiện cả ứng viên đã loại
          </label>
        </div>
        {error && (
          <Notice tone="rust" className="m-3">
            {error}
          </Notice>
        )}
        <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
          {visible.map((object) => (
            <li
              key={object.id}
              id={`object-${object.id}`}
              className={cn("cursor-pointer space-y-2 px-4 py-3", object.id === selected && "bg-ember-soft/40")}
              onClick={() => selectFromList(object)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium text-ink">{object.name}</span>
                <StateBadge object={object} />
              </div>
              <p className="text-xs text-ink-muted">{describe(object)}</p>
              <div className="flex flex-wrap gap-1.5">
                {object.state === "CANDIDATE" && !isIgnored(object) && (
                  <>
                    <Button size="sm" disabled={busy} onClick={() => act(object, "confirm")}>
                      <Check aria-hidden /> Xác nhận
                    </Button>
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => act(object, "ignore")}>
                      <X aria-hidden /> Loại
                    </Button>
                  </>
                )}
                {object.state === "CONFIRMED" && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => act(object, "hide", { active: !object.active })}
                  >
                    {object.active ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
                    {object.active ? "Ẩn khỏi mô phỏng" : "Đưa lại vào mô phỏng"}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
        <SimulationPackagePanel
          jobId={jobId}
          sceneRevision={scene.scene_revision}
          onSceneChanged={() => setReload((value) => value + 1)}
        />
        <AddObstacleForm
          busy={busy}
          onAdd={(name, dimensions, center) =>
            run((revision) => addBoxObstacle(jobId, revision, name, dimensions, center))
          }
        />
      </aside>
    </div>
  );
}

const SELECTED_COLOR = "#f97316";

/** Màu hộp theo trạng thái review: vàng = ứng viên, xanh lá = đã xác nhận, xám = đã loại/ẩn. */
function stateColor(object: SceneObject): string {
  if (isIgnored(object) || !object.active && object.state === "CONFIRMED") return "#9ca3af";
  return object.state === "CONFIRMED" ? "#22c55e" : "#facc15";
}

function isIgnored(object: SceneObject): boolean {
  return object.provenance.review === "IGNORED";
}

function describe(object: SceneObject): string {
  const [x, y, z] = object.transform.translation_xyz;
  const size = object.primitive_dimensions_xyz_m?.map((value) => value.toFixed(2)).join(" × ");
  return `Tâm (${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)}) m${size ? ` · ${size} m` : ""}`;
}

function StateBadge({ object }: { object: SceneObject }) {
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
