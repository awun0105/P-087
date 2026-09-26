/**
 * AddObstacleForm — form thêm obstacle/user-added object vào scene (PRODUCT-07A).
 *
 * Gọi fake endpoint `/api/v1/jobs/{jobId}/scene/objects` (POST).
 * Backend stub sẽ được thay bằng SCENE-08A add-object contract khi sẵn sàng.
 *
 * State ownership: mọi thay đổi persist qua backend SceneIR revision.
 * React state chỉ giữ form input + busy/error.
 */

"use client";

import { useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import type { ColliderType } from "@/lib/contracts/api";

const COLLIDER_TYPES: ColliderType[] = ["AABB", "OBB", "CONVEX_HULL", "SIMPLIFIED_MESH"];

interface ObstacleFormData {
  name: string;
  width: string; // m
  depth: string; // m
  height: string; // m
  collider_type: ColliderType;
  pos_x: string;
  pos_y: string;
  pos_z: string;
}

const DEFAULT_FORM: ObstacleFormData = {
  name: "",
  width: "0.5",
  depth: "0.5",
  height: "1.0",
  collider_type: "AABB",
  pos_x: "0.0",
  pos_y: "0.0",
  pos_z: "0.0",
};

const inputCls =
  "w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-100 focus:border-sky-600 focus:outline-none";

export function AddObstacleForm({
  jobId,
  sceneRevision,
  onDone,
}: {
  jobId: string;
  sceneRevision: string;
  onDone: () => void;
}) {
  const [form, setForm] = useState<ObstacleFormData>(DEFAULT_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  function update(field: keyof ObstacleFormData, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    // Client-side validation
    const dims = [form.width, form.depth, form.height].map(Number);
    const pos = [form.pos_x, form.pos_y, form.pos_z].map(Number);
    if (!form.name.trim()) {
      setError("Tên object không được để trống.");
      return;
    }
    if (dims.some((v) => Number.isNaN(v) || v <= 0)) {
      setError("Kích thước (rộng/sâu/cao) phải là số dương.");
      return;
    }
    if (pos.some((v) => Number.isNaN(v))) {
      setError("Tọa độ vị trí phải là số.");
      return;
    }

    const payload = {
      expected_scene_revision: sceneRevision,
      name: form.name.trim(),
      origin: "user_added",
      dimensions_xyz_m: dims as [number, number, number],
      collider_type: form.collider_type,
      position_xyz: pos as [number, number, number],
    };

    setBusy(true);
    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/scene/objects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = (await res.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          // ignore
        }
        throw new ApiError(res.status, detail);
      }
      const data = (await res.json()) as { scene_revision?: string };
      setSuccess(`Đã thêm "${form.name}" vào revision ${data.scene_revision ?? "mới"}.`);
      setForm(DEFAULT_FORM);
      setTimeout(onDone, 800);
    } catch (cause) {
      setError(
        cause instanceof ApiError ? `${cause.status}: ${cause.detail}` : String(cause),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => { void submit(e); }} className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Thêm obstacle</h3>

      {/* Name */}
      <Field label="Tên object *">
        <input
          value={form.name}
          onChange={(e) => update("name", e.target.value)}
          placeholder="Box pallet A"
          required
          className={inputCls}
          aria-label="Tên object"
        />
      </Field>

      {/* Dimensions */}
      <Field label="Kích thước (m) — rộng × sâu × cao">
        <div className="grid grid-cols-3 gap-1.5">
          <input
            value={form.width}
            onChange={(e) => update("width", e.target.value)}
            placeholder="rộng"
            className={inputCls}
            aria-label="Chiều rộng"
          />
          <input
            value={form.depth}
            onChange={(e) => update("depth", e.target.value)}
            placeholder="sâu"
            className={inputCls}
            aria-label="Chiều sâu"
          />
          <input
            value={form.height}
            onChange={(e) => update("height", e.target.value)}
            placeholder="cao"
            className={inputCls}
            aria-label="Chiều cao"
          />
        </div>
      </Field>

      {/* Position */}
      <Field label="Vị trí (m) — X Y Z">
        <div className="grid grid-cols-3 gap-1.5">
          <input
            value={form.pos_x}
            onChange={(e) => update("pos_x", e.target.value)}
            placeholder="X"
            className={inputCls}
            aria-label="X"
          />
          <input
            value={form.pos_y}
            onChange={(e) => update("pos_y", e.target.value)}
            placeholder="Y"
            className={inputCls}
            aria-label="Y"
          />
          <input
            value={form.pos_z}
            onChange={(e) => update("pos_z", e.target.value)}
            placeholder="Z"
            className={inputCls}
            aria-label="Z"
          />
        </div>
      </Field>

      {/* Collider type */}
      <Field label="Loại collider">
        <select
          value={form.collider_type}
          onChange={(e) => update("collider_type", e.target.value as ColliderType)}
          className={inputCls}
          aria-label="Loại collider"
        >
          {COLLIDER_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </Field>

      {/* Preview payload */}
      <details className="text-[10px] text-slate-600">
        <summary className="cursor-pointer hover:text-slate-400">Xem payload sẽ gửi</summary>
        <pre className="mt-1 overflow-x-auto rounded bg-slate-950 p-2 text-[10px] text-slate-500">
          {JSON.stringify(
            {
              name: form.name || "(chưa nhập)",
              dimensions_xyz_m: [form.width, form.depth, form.height],
              collider_type: form.collider_type,
              position_xyz: [form.pos_x, form.pos_y, form.pos_z],
              expected_scene_revision: sceneRevision,
            },
            null,
            2,
          )}
        </pre>
      </details>

      {/* Feedback */}
      {error && (
        <p
          data-testid="add-obstacle-error"
          role="alert"
          className="rounded-lg bg-rose-950/60 p-2 text-xs text-rose-300"
        >
          {error}
        </p>
      )}
      {success && (
        <p
          data-testid="add-obstacle-success"
          className="rounded-lg bg-emerald-950/60 p-2 text-xs text-emerald-300"
        >
          {success}
        </p>
      )}

      <Button type="submit" busy={busy} className="w-full">
        {busy ? "Đang thêm…" : "Thêm vào scene"}
      </Button>

      <p className="text-[10px] text-slate-600">
        Endpoint <span className="font-mono">/scene/objects POST</span> là fake stub — sẽ trả 404
        cho đến khi SCENE-08A implement. Revision và payload vẫn được gửi đúng.
      </p>
    </form>
  );
}
