"use client";

/**
 * Màn hình viewer của Web Studio (PRODUCT-06).
 *
 * Phân chia state có chủ ý:
 * - **Canonical** (SceneIR, revision, checksum) đến từ server qua props và chỉ
 *   đổi bằng `router.refresh()` sau khi backend publish revision mới.
 * - **View preference** (view mode, ẩn/hiện layer, đang chọn object nào) nằm
 *   trong React state. Đây là lựa chọn xem, không bao giờ được persist thành
 *   business truth.
 */

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
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
  type ViewMode,
} from "@/features/viewer/layers";
import { parseAsciiPly, type PlyCloud } from "@/features/viewer/ply";
import { SceneCanvas } from "@/features/viewer/SceneCanvas";

export interface ViewerPanelProps {
  scene: SceneResponse;
}

type WebGLState = "checking" | "ok" | "unavailable";

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

/** Năng lực WebGL không đổi trong vòng đời một trang, nên không có gì để subscribe. */
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

  const layers = useMemo(() => buildSceneLayers(scene.scene, scene.scene_checksum), [scene]);
  const shown = useMemo(
    () => visibleLayers(layers, mode).filter((layer) => !hidden.has(layerKey(layer))),
    [layers, mode, hidden],
  );

  // WebGL là năng lực của trình duyệt, không phải state của React. Đọc qua
  // `useSyncExternalStore`: server render "checking" rồi client tự chốt sau
  // hydration — vừa tránh lệch hydration, vừa không phải setState trong effect.
  // Cache theo từng instance để mỗi lần render không tạo thêm một canvas vứt đi.
  const webglCache = useRef<WebGLState | null>(null);
  const readWebgl = useCallback((): WebGLState => {
    webglCache.current ??= detectWebGL();
    return webglCache.current;
  }, []);
  const webgl = useSyncExternalStore(subscribeToNothing, readWebgl, serverWebglSnapshot);

  // Nạp point cloud qua endpoint content: backend verify checksum trước khi trả.
  useEffect(() => {
    if (mode !== "POINT_CLOUD" && mode !== "GEOMETRY") {
      return;
    }
    const targets = visibleLayers(layers, mode);
    let cancelled = false;
    for (const layer of targets) {
      // GEOMETRY/POINT_CLOUD chỉ trả layer có geometry_ref; collider có thể null.
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

  const selectedLayer = shown.find((layer) => layerKey(layer) === selected) ?? null;
  const selectedObject = selectedLayer?.object_id
    ? scene.scene.objects.find((item) => item.id === selectedLayer.object_id)
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

  async function submitEdit() {
    if (!selectedObject) {
      return;
    }
    const parts = translation.split(",").map((value) => Number.parseFloat(value.trim()));
    if (parts.length !== 3 || parts.some((value) => Number.isNaN(value))) {
      setEditError("toạ độ phải là ba số, cách nhau bằng dấu phẩy — ví dụ: 3.0, 2.0, 0.0");
      return;
    }
    setEditBusy(true);
    setEditError(null);
    try {
      await editScene(scene.job_id, {
        expected_scene_revision: scene.scene_revision,
        edits: [{ object_id: selectedObject.id, translation_xyz: [parts[0]!, parts[1]!, parts[2]!] }],
      });
      setTranslation("");
      router.refresh();
    } catch (cause) {
      setEditError(
        cause instanceof ApiError ? `${cause.status}: ${cause.detail}` : `lỗi không xác định: ${String(cause)}`,
      );
    } finally {
      setEditBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <section className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
        <header className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-3 py-2">
          {VIEW_MODES.map((candidate) => (
            <button
              key={candidate}
              type="button"
              onClick={() => setMode(candidate)}
              aria-pressed={mode === candidate}
              className={`rounded px-2 py-1 text-xs ${
                mode === candidate ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {VIEW_MODE_LABELS[candidate]}
            </button>
          ))}
          <span className="ml-auto font-mono text-xs text-slate-400" data-testid="scene-revision">
            {scene.scene_revision}
          </span>
        </header>

        <div className="h-[28rem]">
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
              onSelect={setSelected}
              mode={mode}
            />
          )}
        </div>
      </section>

      <aside className="flex flex-col gap-4">
        <VisualBanner scene={scene} />
        <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
          <h3 className="mb-2 text-sm font-semibold text-slate-200">Layer</h3>
          <ul className="flex flex-col gap-1 text-xs">
            {[...layers.geometry, ...layers.colliders].map((layer) => {
              const key = layerKey(layer);
              return (
                <li key={key} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={!hidden.has(key)}
                    onChange={() => toggle(key)}
                    aria-label={`hiện ${layer.label}`}
                  />
                  <button
                    type="button"
                    onClick={() => setSelected(key)}
                    className={`flex-1 truncate text-left ${selected === key ? "text-amber-400" : "text-slate-300"}`}
                  >
                    {layer.label}
                  </button>
                  <span className="font-mono text-[10px] text-slate-500">
                    {layer.checksum ? layer.checksum.slice(7, 15) : "no-ref"}
                  </span>
                </li>
              );
            })}
          </ul>
          {Object.entries(plyErrors).map(([key, message]) => (
            <p key={key} className="mt-2 text-xs text-rose-400">
              {key}: không đọc được geometry — {message}
            </p>
          ))}
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
          <h3 className="mb-2 text-sm font-semibold text-slate-200">Transform edit</h3>
          {selectedObject ? (
            <>
              <p className="mb-2 text-xs text-slate-400">
                {selectedObject.name} · hiện tại [{selectedObject.transform.translation_xyz.join(", ")}]
              </p>
              <input
                value={translation}
                onChange={(event) => setTranslation(event.target.value)}
                placeholder="3.0, 2.0, 0.0"
                aria-label="translation xyz"
                className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
              />
              <button
                type="button"
                onClick={submitEdit}
                disabled={editBusy}
                className="mt-2 w-full rounded bg-sky-600 px-2 py-1 text-xs text-white disabled:opacity-50"
              >
                {editBusy ? "Đang gửi…" : "Lưu thành revision mới"}
              </button>
              <p className="mt-2 text-[10px] text-slate-500">
                Gửi kèm `expected_scene_revision = {scene.scene_revision}`; backend từ chối 409 nếu revision đã đổi.
              </p>
            </>
          ) : (
            <p className="text-xs text-slate-400">Chọn một object trong danh sách layer để sửa.</p>
          )}
          {editError && (
            <p role="alert" className="mt-2 rounded bg-rose-950/60 p-2 text-xs text-rose-300">
              {editError}
            </p>
          )}
        </section>
      </aside>
    </div>
  );
}

function DegradedState() {
  return (
    <div className="p-4 text-sm text-amber-300" data-testid="webgl-unavailable">
      Trình duyệt không cấp được WebGL/WebGL2 context. Viewer không thể dựng hình — đây là trạng thái
      suy giảm, không phải bằng chứng render.
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
        Chưa có renderer Gaussian: AC-11 cần real Brush `VisualArtifact` do EX-REC publish (REC-04), và đó là
        mốc M3. Fixture hiện tại không được tính là bằng chứng render 3DGS.
      </p>
    </div>
  );
}

function VisualBanner({ scene }: { scene: SceneResponse }) {
  if (scene.visual.available && scene.visual.brush_compatibility_proof) {
    return (
      <p className="rounded-lg border border-emerald-800 bg-emerald-950/50 p-3 text-xs text-emerald-200">
        Visual gắn cờ bằng chứng Brush.
      </p>
    );
  }
  return (
    <p
      className="rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200"
      data-testid="brush-proof-absent"
    >
      <strong>Chưa có bằng chứng 3DGS thật.</strong> Visual hiện tại là bản tổng hợp (
      <span className="font-mono">{scene.visual.format ?? "không có"}</span>
      <span className="font-mono"> brush_compatibility_proof=false</span>). Các view Geometry/Point
      Cloud/Collider là view kỹ thuật ngang hàng, không phải fallback và không thay thế AC-11.
    </p>
  );
}
