"use client";

/**
 * Màn hình viewer của Web Studio (PRODUCT-06 + PRODUCT-07).
 *
 * Phân chia state có chủ ý:
 * - **Canonical** (SceneIR, revision, checksum) đến từ server qua props và chỉ
 *   đổi bằng `router.refresh()` sau khi backend publish revision mới.
 * - **View preference** (view mode, ẩn/hiện layer, đang chọn object nào) nằm
 *   trong React state. Đây là lựa chọn xem, không bao giờ được persist thành
 *   business truth.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { editScene, jobArtifactContentUrl } from "@/lib/api/endpoints";
import type { SceneResponse } from "@/lib/contracts/api";
import {
  buildSceneLayers,
  layerKey,
  VIEW_MODE_LABELS,
  VIEW_MODES,
  visibleLayers,
  type GeometryLayer,
  type ColliderLayer,
  type ViewMode,
} from "@/features/viewer/layers";
import { parseAsciiPly, type PlyCloud } from "@/features/viewer/ply";
import { SceneCanvas } from "@/features/viewer/SceneCanvas";
import { ObjectActionsPanel } from "@/features/scene/ObjectActions";
import { AddObstacleForm } from "@/features/scene/AddObstacle";
import { SceneGraph } from "@/features/scene/SceneGraph";
import { MetricScalePanel } from "@/features/scene/MetricScalePanel";
import { MockReadonlyPanel } from "@/features/scene/MockReadonlyPanel";
import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";

export interface ViewerPanelProps {
  scene: SceneResponse;
}

type WebGLState = "checking" | "ok" | "unavailable";
type SidePanel = "layers" | "transform" | "actions" | "add" | "graph" | "metric";

function detectWebGL(): WebGLState {
  if (typeof window === "undefined") {
    return "checking";
  }
  try {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    return context ? "ok" : "unavailable";
  } catch {
    return "unavailable";
  }
}

/** Năng lực WebGL không đổi trong vòng đờ một trang, nên không có gì để subscribe. */
function subscribeToNothing(): () => void {
  return () => {};
}

function serverWebglSnapshot(): WebGLState {
  return "checking";
}

export function ViewerPanel({ scene }: ViewerPanelProps) {
  const router = useRouter();
  const [mode, setMode] = useState<ViewMode>("COLLIDER");
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [clouds, setClouds] = useState<Record<string, PlyCloud>>({});
  const [plyErrors, setPlyErrors] = useState<Record<string, string>>({});
  const [editError, setEditError] = useState<string | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [translation, setTranslation] = useState("");
  const [sidePanel, setSidePanel] = useState<SidePanel>("layers");
  const [layerQuery, setLayerQuery] = useState("");

  const layers = useMemo(() => buildSceneLayers(scene.scene, scene.scene_checksum), [scene]);
  const shown = useMemo(
    () => visibleLayers(layers, mode).filter((layer) => !hidden.has(layerKey(layer))),
    [layers, mode, hidden],
  );

  const webglCache = useRef<WebGLState | null>(null);
  const readWebgl = useCallback((): WebGLState => {
    webglCache.current ??= detectWebGL();
    return webglCache.current;
  }, []);
  const webgl = useSyncExternalStore(subscribeToNothing, readWebgl, serverWebglSnapshot);

  // Nạp point cloud qua endpoint content
  useEffect(() => {
    if (mode !== "POINT_CLOUD" && mode !== "GEOMETRY") {
      return;
    }
    const targets = visibleLayers(layers, mode);
    let cancelled = false;
    for (const layer of targets) {
      if (!layer.reference) {
        continue;
      }
      const key = layerKey(layer);
      if (clouds[key] || plyErrors[key]) {
        continue;
      }
      const url = jobArtifactContentUrl(scene.job_id, layer.reference);
      fetch(url)
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          return parseAsciiPly(await response.text());
        })
        .then((cloud) => {
          if (!cancelled) {
            setClouds((current) => ({ ...current, [key]: cloud }));
          }
        })
        .catch((cause: unknown) => {
          if (!cancelled) {
            setPlyErrors((current) => ({ ...current, [key]: String(cause) }));
          }
        });
    }
    return () => {
      cancelled = true;
    };
  }, [layers, mode, scene.job_id, clouds, plyErrors]);

  // Resolve selection từ toàn bộ layers (không chỉ shown) để Scene Graph có thể chọn
  // object ngay cả khi mode hiện tại không render layer đó.
  const selectedLayer = layers.all.find((layer) => layerKey(layer) === selected) ?? null;
  const selectedObject = selectedLayer?.object_id
    ? scene.scene.objects.find((item) => item.id === selectedLayer.object_id) ?? null
    : null;

  function toggle(key: string) {
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function showOnly(key: string) {
    setHidden(new Set(layers.all.map(layerKey).filter((k) => k !== key)));
  }

  function showAll() {
    setHidden(new Set());
  }

  function hideAll() {
    setHidden(new Set(layers.all.map(layerKey)));
  }

  function handleSelect(key: string | null) {
    setSelected(key);
    // Khi chọn object từ layer list, chuyển sang transform tab để dễ edit.
    if (key) setSidePanel("transform");
  }

  function selectObject(objectId: string | null) {
    if (!objectId) {
      setSelected(null);
      return;
    }
    // Ưu tiên collider, fallback geometry/point-cloud để object không collider vẫn chọn được.
    const candidates = layers.all.filter((l) => l.object_id === objectId);
    const layer =
      candidates.find((l) => l.kind === "collider") ??
      candidates.find((l) => l.kind === "geometry") ??
      candidates[0];
    if (!layer) {
      setSelected(null);
      return;
    }
    setSelected(layerKey(layer));
    setSidePanel("transform");
  }

  function applyNudge(axis: 0 | 1 | 2, delta: number) {
    if (!selectedObject) return;
    const current = selectedObject.transform.translation_xyz;
    const next: [number, number, number] = [...current];
    next[axis] = Number((next[axis] + delta).toFixed(3));
    submitTranslation(next);
  }

  function resetToCanonical() {
    if (!selectedObject) return;
    submitTranslation(selectedObject.transform.translation_xyz);
  }

  async function submitTranslation(target: [number, number, number]) {
    if (!selectedObject) return;
    setEditBusy(true);
    setEditError(null);
    try {
      await editScene(scene.job_id, {
        expected_scene_revision: scene.scene_revision,
        edits: [{ object_id: selectedObject.id, translation_xyz: target }],
      });
      setTranslation("");
      router.refresh();
    } catch (cause) {
      setEditError(
        cause instanceof ApiError
          ? `${cause.status}: ${cause.detail}`
          : `lỗi không xác định: ${String(cause)}`,
      );
    } finally {
      setEditBusy(false);
    }
  }

  async function submitEdit() {
    if (!selectedObject) {
      return;
    }
    const parts = translation.split(",").map((value) => Number.parseFloat(value.trim()));
    if (parts.length !== 3 || parts.some((value) => Number.isNaN(value))) {
      setEditError("toạ độ phải là ba số, cách nhau bằng dấu phẩy — ví dụ: 3.0, 2.0, 0.0");
      return;
    }
    await submitTranslation([parts[0]!, parts[1]!, parts[2]!]);
  }

  // Keyboard shortcuts
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const tag = (event.target as HTMLElement)?.tagName?.toLowerCase();
      if (["input", "textarea", "select"].includes(tag)) {
        return;
      }
      switch (event.key) {
        case "1":
          setMode("COLLIDER");
          break;
        case "2":
          setMode("GEOMETRY");
          break;
        case "3":
          setMode("POINT_CLOUD");
          break;
        case "4":
          setMode("VISUAL");
          break;
        case "h":
        case "H":
          if (selected) {
            toggle(selected);
          }
          break;
        case "Escape":
          setSelected(null);
          break;
        case "f":
        case "F":
          if (selectedObject) {
            // Focus là view preference — hiện tại chỉ giữ lại selection.
            setSidePanel("transform");
          }
          break;
        default:
          return;
      }
      event.preventDefault();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selected, selectedObject]);

  const allLayers = [...layers.geometry, ...layers.colliders];
  const filteredLayers = layerQuery
    ? allLayers.filter((layer) => layer.label.toLowerCase().includes(layerQuery.toLowerCase()))
    : allLayers;

  const objectCounts = useMemo(() => {
    const total = scene.scene.objects.length;
    const confirmed = scene.scene.objects.filter((o) => o.state === "CONFIRMED").length;
    const candidate = scene.scene.objects.filter((o) => o.state === "CANDIDATE").length;
    const hiddenCount = scene.scene.objects.filter((o) => !o.active).length;
    return { total, confirmed, candidate, hiddenCount };
  }, [scene]);

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr_22rem]">
      {/* ── Left: Scene Graph + Metric Scale (wireframe Screen 2) ── */}
      <aside className="order-2 flex flex-col gap-3 lg:order-1">
        <Panel>
          <div className="p-3">
            <PanelHeader title="Scene Graph" subtitle="click object để chọn" />
            <SceneGraph
              scene={scene.scene}
              selectedObjectId={selectedObject?.id ?? null}
              onSelect={selectObject}
            />
          </div>
        </Panel>

        <MetricScalePanel metricScale={scene.scene.metric_scale} />

        <MockReadonlyPanel
          title="AMR Validation Setup"
          reason="Start–Goal locking / footprint / AMR route validation thuộc Foundation Lock & EX-SIM, chưa có endpoint backend."
        />

        <MockReadonlyPanel
          title="Deterministic Audit"
          reason="Dữ liệu audit checklist thật nằm trong PreflightReport, backend chưa expose endpoint."
        />
      </aside>

      {/* ── Center: 3D Canvas ── */}
      <section className="order-1 flex flex-col gap-3 lg:order-2">
        <Panel className="overflow-hidden">
          <header className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-3 py-2">
            {VIEW_MODES.map((candidate) => (
              <button
                key={candidate}
                type="button"
                onClick={() => setMode(candidate)}
                aria-pressed={mode === candidate}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-all ${
                  mode === candidate
                    ? "bg-sky-600 text-white shadow-sm"
                    : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
                }`}
              >
                {VIEW_MODE_LABELS[candidate]}
              </button>
            ))}
            <span className="ml-auto rounded bg-slate-900 px-2 py-0.5 font-mono text-xs text-slate-500">
              <kbd className="font-sans text-[10px] text-slate-600">1-4</kbd>
            </span>
            <span
              className="rounded bg-slate-900 px-2 py-0.5 font-mono text-xs text-slate-500"
              data-testid="scene-revision"
            >
              {scene.scene_revision}
            </span>
          </header>

          <div className="h-[30rem]">
            {webgl === "unavailable" ? (
              <DegradedState />
            ) : webgl === "checking" ? (
              <p className="p-4 text-sm text-slate-400">Đang kiểm tra WebGL…</p>
            ) : mode === "VISUAL" ? (
              <VisualUnavailable scene={scene} />
            ) : shown.length === 0 ? (
              <p className="p-4 text-sm text-slate-400" data-testid="no-layers">
                View này không có layer nào đang bật.
              </p>
            ) : (
              <SceneCanvas
                layers={shown}
                clouds={clouds}
                selectedKey={selected}
                onSelect={handleSelect}
                mode={mode}
              />
            )}
          </div>
        </Panel>

        {/* Object count summary */}
        <Panel>
          <div className="flex gap-3 flex-wrap px-4 py-3">
            <Stat label="Tổng" value={objectCounts.total} color="text-slate-300" />
            <Stat
              label="CONFIRMED"
              value={objectCounts.confirmed}
              color="text-emerald-400"
            />
            <Stat label="CANDIDATE" value={objectCounts.candidate} color="text-amber-400" />
            <Stat label="Ẩn" value={objectCounts.hiddenCount} color="text-slate-500" />
          </div>
        </Panel>
      </section>

      {/* ── Right Sidebar ── */}
      <aside className="order-3 flex flex-col gap-3">
        <VisualBanner scene={scene} />

        {/* Side panel tabs */}
        <Panel className="overflow-hidden">
          <div className="flex border-b border-slate-800">
            {sidePanelTabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setSidePanel(tab.key)}
                className={`flex flex-1 items-center justify-center gap-1 py-2 text-xs font-medium transition-all ${
                  sidePanel === tab.key
                    ? "border-b-2 border-sky-600 bg-slate-800 text-sky-400"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                <span>{tab.icon}</span>
                <span className="hidden sm:inline">{tab.label}</span>
              </button>
            ))}
          </div>

          <div className="p-3">
            {sidePanel === "layers" && (
              <LayerPanel
                layers={filteredLayers}
                hidden={hidden}
                selected={selected}
                onToggle={toggle}
                onSelect={handleSelect}
                onShowOnly={showOnly}
                onShowAll={showAll}
                onHideAll={hideAll}
                plyErrors={plyErrors}
                query={layerQuery}
                setQuery={setLayerQuery}
              />
            )}

            {sidePanel === "transform" && (
              <TransformPanel
                selectedObject={selectedObject ?? null}
                translation={translation}
                setTranslation={setTranslation}
                onSubmit={submitEdit}
                onNudge={applyNudge}
                onReset={resetToCanonical}
                busy={editBusy}
                error={editError}
                sceneRevision={scene.scene_revision}
              />
            )}

            {sidePanel === "actions" && selectedObject ? (
              <ObjectActionsPanel
                jobId={scene.job_id}
                sceneRevision={scene.scene_revision}
                object={selectedObject}
                onDeselect={() => {
                  setSelected(null);
                  setSidePanel("layers");
                }}
              />
            ) : sidePanel === "actions" ? (
              <p className="py-2 text-xs text-slate-500">
                Chọn một object trong Scene hoặc tab Layer trước.
              </p>
            ) : null}

            {sidePanel === "add" && (
              <AddObstacleForm
                jobId={scene.job_id}
                sceneRevision={scene.scene_revision}
                onDone={() => {
                  router.refresh();
                  setSidePanel("layers");
                }}
              />
            )}

            {sidePanel === "graph" && (
              <SceneGraph
                scene={scene.scene}
                selectedObjectId={selectedObject?.id ?? null}
                onSelect={selectObject}
              />
            )}

            {sidePanel === "metric" && (
              <>
                <MetricScalePanel metricScale={scene.scene.metric_scale} />
                <div className="mt-3">
                  <MockReadonlyPanel
                    title="AMR Validation Setup"
                    reason="Start–Goal locking / footprint / AMR route validation thuộc Foundation Lock & EX-SIM, chưa có endpoint backend."
                  />
                </div>
              </>
            )}
          </div>
        </Panel>
      </aside>
    </div>
  );
}

const sidePanelTabs: { key: SidePanel; label: string; icon: string }[] = [
  { key: "layers", label: "Layer", icon: "☰" },
  { key: "transform", label: "Transform", icon: "⊕" },
  { key: "actions", label: "Actions", icon: "⚡" },
  { key: "add", label: "Thêm", icon: "+" },
];

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="text-center">
      <p className={`text-lg font-bold ${color}`}>{value}</p>
      <p className="text-[10px] text-slate-600">{label}</p>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────

function LayerPanel({
  layers,
  hidden,
  selected,
  onToggle,
  onSelect,
  onShowOnly,
  onShowAll,
  onHideAll,
  plyErrors,
  query,
  setQuery,
}: {
  layers: (GeometryLayer | ColliderLayer)[];
  hidden: ReadonlySet<string>;
  selected: string | null;
  onToggle: (key: string) => void;
  onSelect: (key: string | null) => void;
  onShowOnly: (key: string) => void;
  onShowAll: () => void;
  onHideAll: () => void;
  plyErrors: Record<string, string>;
  query: string;
  setQuery: (v: string) => void;
}) {
  return (
    <>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Layer</h3>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={onShowAll}
            className="rounded px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-800 hover:text-slate-300"
            title="Hiện tất cả"
          >
            all
          </button>
          <button
            type="button"
            onClick={onHideAll}
            className="rounded px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-800 hover:text-slate-300"
            title="Ẩn tất cả"
          >
            none
          </button>
        </div>
      </div>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="lọc layer…"
        className="mb-2 w-full rounded border border-slate-800 bg-slate-950 px-2 py-1 text-xs text-slate-200 focus:border-sky-600 focus:outline-none"
      />
      <ul className="flex flex-col gap-0.5 text-xs">
        {layers.map((layer) => {
          const key = layerKey(layer);
          return (
            <li key={key} className="group flex items-center gap-2">
              <input
                type="checkbox"
                checked={!hidden.has(key)}
                onChange={() => onToggle(key)}
                aria-label={`hiện ${layer.label}`}
                className="shrink-0"
              />
              <button
                type="button"
                onClick={() => onSelect(selected === key ? null : key)}
                className={`flex-1 truncate py-0.5 text-left transition-colors ${
                  selected === key ? "font-medium text-amber-400" : "text-slate-300 group-hover:text-slate-100"
                }`}
              >
                {layer.label}
              </button>
              <button
                type="button"
                onClick={() => onShowOnly(key)}
                className="rounded px-1 text-[10px] text-slate-600 opacity-0 transition-opacity hover:bg-slate-800 hover:text-slate-300 group-hover:opacity-100"
                title="Chỉ hiện layer này"
              >
                only
              </button>
              <span className="shrink-0 font-mono text-[10px] text-slate-600">
                {layer.checksum ? layer.checksum.slice(7, 15) : "no-ref"}
              </span>
            </li>
          );
        })}
      </ul>
      {Object.entries(plyErrors).map(([key, message]) => (
        <p key={key} className="mt-2 text-xs text-rose-400">
          {key}: không đọc được — {message}
        </p>
      ))}
    </>
  );
}

function TransformPanel({
  selectedObject,
  translation,
  setTranslation,
  onSubmit,
  onNudge,
  onReset,
  busy,
  error,
  sceneRevision,
}: {
  selectedObject: { name: string; id: string; transform: { translation_xyz: [number, number, number] } } | null;
  translation: string;
  setTranslation: (v: string) => void;
  onSubmit: () => void;
  onNudge: (axis: 0 | 1 | 2, delta: number) => void;
  onReset: () => void;
  busy: boolean;
  error: string | null;
  sceneRevision: string;
}) {
  return (
    <>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Transform Edit
      </h3>
      {selectedObject ? (
        <>
          <p className="mb-2 text-xs text-slate-400">
            <span className="text-slate-200">{selectedObject.name}</span> · hiện tại [
            {selectedObject.transform.translation_xyz.join(", ")}]
          </p>

          {/* Nudge buttons */}
          <div className="mb-2 grid grid-cols-3 gap-1 text-[10px]">
            {([0, 1, 2] as const).map((axis) => (
              <div key={axis} className="flex flex-col gap-1">
                <span className="text-center text-[10px] text-slate-600">
                  {["X", "Y", "Z"][axis]}
                </span>
                <div className="flex gap-0.5">
                  <button
                    type="button"
                    onClick={() => onNudge(axis, -0.1)}
                    className="flex-1 rounded bg-slate-800 py-1 text-slate-300 hover:bg-slate-700"
                    title="-0.1"
                  >
                    −0.1
                  </button>
                  <button
                    type="button"
                    onClick={() => onNudge(axis, 0.1)}
                    className="flex-1 rounded bg-slate-800 py-1 text-slate-300 hover:bg-slate-700"
                    title="+0.1"
                  >
                    +0.1
                  </button>
                </div>
                <div className="flex gap-0.5">
                  <button
                    type="button"
                    onClick={() => onNudge(axis, -0.5)}
                    className="flex-1 rounded bg-slate-800/60 py-1 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
                    title="-0.5"
                  >
                    −0.5
                  </button>
                  <button
                    type="button"
                    onClick={() => onNudge(axis, 0.5)}
                    className="flex-1 rounded bg-slate-800/60 py-1 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
                    title="+0.5"
                  >
                    +0.5
                  </button>
                </div>
              </div>
            ))}
          </div>

          <input
            value={translation}
            onChange={(event) => setTranslation(event.target.value)}
            placeholder="3.0, 2.0, 0.0"
            aria-label="translation xyz"
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-100 focus:border-sky-600 focus:outline-none"
          />
          <div className="mt-2 flex gap-2">
            <Button variant="primary" size="sm" busy={busy} onClick={onSubmit} className="flex-1">
              Lưu thành revision mới
            </Button>
            <Button variant="subtle" size="sm" onClick={onReset}>
              Reset
            </Button>
          </div>
          <p className="mt-2 text-[10px] text-slate-600">revision: {sceneRevision}</p>
        </>
      ) : (
        <p className="text-xs text-slate-500">Chọn object trong tab Layer để sửa transform.</p>
      )}
      {error && (
        <p role="alert" className="mt-2 rounded-lg bg-rose-950/60 p-2 text-xs text-rose-300">
          {error}
        </p>
      )}
    </>
  );
}

function DegradedState() {
  return (
    <div className="p-4 text-sm text-amber-300" data-testid="webgl-unavailable">
      Trình duyệt không cấp được WebGL/WebGL2 context. Viewer không thể dựng hình — đây là trạng
      thái suy giảm, không phải bằng chứng render.
    </div>
  );
}

function VisualUnavailable({ scene }: { scene: SceneResponse }) {
  return (
    <div className="p-4 text-sm text-slate-300" data-testid="visual-view">
      <p className="mb-2">
        Visual hiện tại: <span className="font-mono">{scene.visual.format ?? "(chưa có)"}</span> từ{" "}
        <span className="font-mono">{scene.visual.producer ?? "không rõ"}</span>.
      </p>
      <p className="text-amber-300">
        Chưa có renderer Gaussian: AC-11 cần real Brush `VisualArtifact` do EX-REC publish (REC-04),
        và đó là mốc M3. Fixture hiện tại không được tính là bằng chứng render 3DGS.
      </p>
    </div>
  );
}

function VisualBanner({ scene }: { scene: SceneResponse }) {
  if (scene.visual.available && scene.visual.brush_compatibility_proof) {
    return (
      <p className="rounded-xl border border-emerald-800 bg-emerald-950/50 p-3 text-xs text-emerald-200">
        Visual gắn cờ bằng chứng Brush.
      </p>
    );
  }
  return (
    <p
      className="rounded-xl border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200"
      data-testid="brush-proof-absent"
    >
      <strong>Chưa có bằng chứng 3DGS thật.</strong> Visual hiện tại là bản tổng hợp (
      <span className="font-mono">{scene.visual.format ?? "không có"}</span>
      <span className="font-mono"> brush_compatibility_proof=false</span>). Các view Geometry/Point
      Cloud/Collider là view kỹ thuật ngang hàng, không phải fallback và không thay thế AC-11.
    </p>
  );
}
