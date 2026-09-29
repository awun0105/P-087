/**
 * ObjectActions — panel hành động HITL cho một SceneObject đã chọn (PRODUCT-07).
 *
 * Các action gọi fake endpoint qua apiFetch; backend stub sẽ
 * được thay thế bởi SCENE operations thật khi SCENE-05/08 hoàn tất.
 *
 * State ownership:
 * - Quyết định (CONFIRMED/CANDIDATE/IGNORED) thuộc backend SceneIR revision.
 * - React state chỉ giữ trạng thái busy/error của lần gọi hiện tại.
 */

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Banner } from "@/components/ui/banner";
import type { SceneObject } from "@/lib/contracts/api";

export interface ObjectActionsProps {
  jobId: string;
  sceneRevision: string;
  object: SceneObject;
  onDeselect: () => void;
}

type ActionKey = "confirm" | "ignore" | "rename" | "hide" | "delete";

async function callObjectAction(
  jobId: string,
  objectId: string,
  action: ActionKey,
  payload?: Record<string, unknown>,
): Promise<void> {
  const url = `/api/v1/jobs/${encodeURIComponent(jobId)}/scene/objects/${encodeURIComponent(objectId)}/${action}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload }),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, detail);
  }
}

export function ObjectActionsPanel({
  jobId,
  sceneRevision,
  object,
  onDeselect,
}: ObjectActionsProps) {
  const router = useRouter();
  const [busy, setBusy] = useState<ActionKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState(object.name);
  const [showRename, setShowRename] = useState(false);

  const isCandidate = object.state === "CANDIDATE";
  const isConfirmed = object.state === "CONFIRMED";

  async function run(action: ActionKey, payload?: Record<string, unknown>) {
    setBusy(action);
    setError(null);
    try {
      await callObjectAction(jobId, object.id, action, {
        expected_scene_revision: sceneRevision,
        ...payload,
      });
      router.refresh();
      onDeselect();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? `${cause.status}: ${cause.detail}`
          : String(cause),
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">{object.name}</h3>
          <div className="mt-1 flex items-center gap-2">
            <StateBadge state={object.state} />
            <Badge tone="muted" className="text-[10px]">
              {object.origin === "user_added" ? "user-added" : "reconstructed"}
            </Badge>
          </div>
        </div>
        <button
          type="button"
          onClick={onDeselect}
          className="px-1 text-sm text-slate-600 hover:text-slate-400"
          aria-label="Bỏ chọn object"
        >
          ×
        </button>
      </div>

      {/* Object info */}
      <div className="mb-3 space-y-0.5 font-mono text-[10px] text-slate-500">
        <p>id: {object.id}</p>
        <p>xyz: {object.transform.translation_xyz.map((v) => v.toFixed(2)).join(", ")}</p>
        {object.collider && <p>collider: {object.collider.collider_type}</p>}
      </div>

      {/* AC-12 warning */}
      <Banner tone="warn" title="Chú ý">
        Xóa / đổi tên object là thay đổi layout. Nền phía sau có thể không khôi phục hoàn toàn.
      </Banner>

      {/* Actions */}
      <div className="mt-3 flex flex-col gap-1.5">
        {isCandidate && (
          <Button
            variant="primary"
            size="sm"
            busy={busy === "confirm"}
            onClick={() => run("confirm")}
          >
            Xác nhận (CONFIRMED)
          </Button>
        )}
        {isConfirmed && (
          <Button
            variant="ghost"
            size="sm"
            busy={busy === "ignore"}
            onClick={() => run("ignore")}
          >
            Chuyển về CANDIDATE
          </Button>
        )}
        {isCandidate && (
          <Button
            variant="ghost"
            size="sm"
            busy={busy === "ignore"}
            onClick={() => run("ignore")}
          >
            Bỏ qua (ignore)
          </Button>
        )}

        {/* Toggle active */}
        <Button
          variant="ghost"
          size="sm"
          busy={busy === "hide"}
          onClick={() => run("hide", { active: !object.active })}
        >
          {object.active ? "Ẩn khỏi scene" : "Hiện lại"}
        </Button>

        {/* Rename inline */}
        {showRename ? (
          <div className="flex gap-1">
            <input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
              placeholder="Tên mới"
              aria-label="Tên mới của object"
            />
            <Button
              variant="primary"
              size="sm"
              busy={busy === "rename"}
              onClick={() => run("rename", { name: renameValue })}
            >
              OK
            </Button>
            <Button variant="subtle" size="sm" onClick={() => setShowRename(false)}>
              Huỷ
            </Button>
          </div>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => setShowRename(true)}>
            Đặt lại tên
          </Button>
        )}

        {/* Delete — destructive */}
        <Button
          variant="danger"
          size="sm"
          busy={busy === "delete"}
          onClick={() => {
            if (window.confirm(`Xóa "${object.name}" khỏi revision? Không hoàn tác.`)) {
              void run("delete");
            }
          }}
        >
          Xóa object
        </Button>
      </div>

      {/* Error */}
      {error && (
        <p role="alert" className="mt-3 rounded-lg bg-rose-950/60 p-2 text-xs text-rose-300">
          {error}
        </p>
      )}

      <p className="mt-3 text-[10px] text-slate-600">
        revision: {sceneRevision} · backend từ chối 409 nếu revision đã đổi.
      </p>
    </section>
  );
}

function StateBadge({ state }: { state: "CANDIDATE" | "CONFIRMED" }) {
  return (
    <Badge tone={state === "CONFIRMED" ? "ok" : "warn"}>
      {state}
    </Badge>
  );
}
