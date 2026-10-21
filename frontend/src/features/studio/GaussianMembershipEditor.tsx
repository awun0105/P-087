"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePolling } from "@/features/studio/usePolling";
import { Button } from "@/components/studio/primitives";
import { cancelObjectify, getObjectifyState, previewMembership, regenerateMembership, type MembershipPreview, type ObjectifyState } from "@/lib/api/studio";
import { jobArtifactContentUrl } from "@/lib/api/endpoints";
import type { ObjectMembershipArtifact, ObjectMembershipReassignCommand, SceneIR } from "@/lib/contracts/api";
import { errorMessage } from "@/lib/ui-error";

/** Selection edits immutable source rows. The embedded editor never writes SceneIR. */
export function GaussianMembershipEditor({ jobId, scene, objectId, onClose, onPublished }: {
  jobId: string; scene: SceneIR; objectId: string; onClose: () => void; onPublished: () => void;
}) {
  const membership = scene.environment.membership as ObjectMembershipArtifact;
  const frame = useRef<HTMLIFrameElement>(null);
  const sequence = useRef(0);
  const pending = useRef<{ id: number; source: string | null; target: string | null } | null>(null);
  const [source, setSource] = useState<string | null>(objectId);
  const [target, setTarget] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ command: ObjectMembershipReassignCommand; preview: MembershipPreview } | null>(null);
  const [operation, setOperation] = useState<ObjectifyState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = operation?.status === "queued" || operation?.status === "running";
  const context = useMemo(() => ({ checksum: membership.source_visual_ref.artifact_checksum, rowCount: membership.gaussian_count }), [membership.source_visual_ref.artifact_checksum, membership.gaussian_count]);
  const src = `/editor/index.html?${new URLSearchParams({
    load: jobArtifactContentUrl(jobId, membership.source_visual_ref), filename: "membership-source.ply",
    membershipSource: context.checksum,
  })}`;
  const owners = scene.objects.filter(item => Object.values(membership.label_to_object_id).includes(item.id) && !["DELETED", "IGNORED", "MERGED"].includes(String(item.provenance.review)));

  useEffect(() => {
    let alive = true;
    const receive = async (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow || event.data?.type !== "supersplat:source-selection") return;
      const request = pending.current;
      if (!request || request.id !== event.data.requestId) return;
      pending.current = null;
      try {
        if (event.data.error) throw new Error(String(event.data.error));
        if (event.data.checksum !== context.checksum || !Array.isArray(event.data.rows) || event.data.rows.length === 0) throw new Error("Chưa chọn Gaussian nguồn.");
        const command: ObjectMembershipReassignCommand = {
          expected_scene_revision: scene.scene_revision, membership_checksum: membership.labels_ref.artifact_checksum,
          source_visual_checksum: context.checksum, source_gaussian_indices: event.data.rows,
          source_object_id: request.source, target_object_id: request.target,
        };
        const preview = await previewMembership(jobId, command);
        if (!alive || sequence.current !== request.id) return;
        setDraft({ command, preview });
        frame.current?.contentWindow?.postMessage({ type: "supersplat:source-highlight", ...context, rows: preview.source_gaussian_indices }, window.location.origin);
      } catch (cause) {
        if (alive) setError(errorMessage(cause, "Không thể xem trước vùng chọn"));
      } finally {
        if (alive) setBusy(false);
      }
    };
    window.addEventListener("message", receive);
    return () => { alive = false; window.removeEventListener("message", receive); };
  }, [jobId, scene.scene_revision, membership.labels_ref.artifact_checksum, context]);

  // T-060: dùng vòng poll chung (dừng khi tab ẩn, không khởi động lại mỗi lần trạng thái đổi), nhịp 3 s.
  const followOperation = useCallback(async (signal: AbortSignal) => {
    if (!operation) return;
    try {
      const next = await getObjectifyState(jobId, signal);
      if (signal.aborted) return;
      if (operation.operation_id && next.operation_id !== operation.operation_id) {
        setOperation({ ...operation, status: "failed", error: "Lần xử lý đã thay đổi; tải scene mới trước khi tiếp tục." });
        return;
      }
      setOperation(next);
      if (next.status === "done" && next.mode === "membership" && next.base_revision === scene.scene_revision && next.result_revision) onPublished();
      if (next.status === "failed") setError(next.error ?? "Tái tạo thất bại; scene cũ được giữ nguyên.");
    } catch (cause) {
      if (!signal.aborted) setError(errorMessage(cause, "Không tải được tiến độ"));
    }
  }, [jobId, onPublished, operation, scene.scene_revision]);
  usePolling(followOperation, 3000, active);

  useEffect(() => {
    if (!busy || !pending.current) return;
    const timer = setTimeout(() => {
      if (pending.current) { pending.current = null; setBusy(false); setError("Chưa nhận được vùng chọn. Chờ scene tải xong rồi thử lại."); }
    }, 15000);
    return () => clearTimeout(timer);
  }, [busy]);

  const reset = () => { sequence.current++; pending.current = null; setDraft(null); setError(null); };
  async function apply() {
    if (!draft || busy || active) return;
    setBusy(true); setError(null);
    try { setOperation(await regenerateMembership(jobId, draft.command)); }
    catch (cause) { setError(errorMessage(cause, "Không thể bắt đầu tái tạo")); }
    finally { setBusy(false); }
  }
  return <div className="absolute inset-0 z-50 flex flex-col bg-viewport" role="dialog" aria-modal="true" aria-label="Chỉnh vùng Gaussian nguồn">
    <div className="space-y-2 border-b border-line-dark bg-viewport-deep p-3 text-xs text-on-dark">
      <div className="flex items-center justify-between gap-3"><strong>Chỉnh Gaussian · {scene.scene_revision}</strong><Button size="sm" variant="secondary" onClick={onClose}>Đóng</Button></div>
      <p>Dữ liệu nguồn tại pose tách ban đầu. Dùng Box, Brush hoặc Lasso trong SuperSplat; vùng sáng là Gaussian được chọn. Chỉnh sửa trong editor chỉ dùng để chọn hàng nguồn.</p>
      <div className="flex flex-wrap items-center gap-3">
        <label>Nguồn <select aria-label="Nguồn Gaussian trực quan" disabled={busy || active} className="bg-viewport" value={source ?? ""} onChange={e => { reset(); setSource(e.target.value || null); }}><option value="">Nền</option>{owners.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Đích <select aria-label="Đích Gaussian trực quan" disabled={busy || active} className="bg-viewport" value={target ?? ""} onChange={e => { reset(); setTarget(e.target.value || null); }}><option value="">Nền</option>{owners.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <Button size="sm" disabled={busy || active || source === target} onClick={() => {
          reset(); setBusy(true);
          pending.current = { id: ++sequence.current, source, target };
          frame.current?.contentWindow?.postMessage({ type: "supersplat:source-selection", requestId: sequence.current, ...context }, window.location.origin);
        }}>Xem trước vùng chọn</Button>
        {draft && <Button size="sm" variant="secondary" disabled={busy || active} onClick={reset}>Chọn lại</Button>}
        {draft && <Button size="sm" disabled={busy || active || operation?.status === "done"} onClick={() => void apply()}>Apply và tái tạo</Button>}
        {active && <Button size="sm" variant="secondary" onClick={() => { void cancelObjectify(jobId, operation?.operation_id).then(setOperation).catch(cause => setError(errorMessage(cause, "Không hủy được"))); }}>Hủy tái tạo</Button>}
      </div>
      {draft && <p role="status">{draft.preview.gaussian_count} Gaussian: {source ?? "Nền"} → {target ?? "Nền"}. Vật bị ảnh hưởng: {draft.preview.affected_object_ids.join(", ")}. Bỏ qua {draft.preview.wrong_owner_count} điểm thuộc vật khác; giữ {draft.preview.protected_count} điểm sàn. Chưa áp dụng thì scene không đổi.</p>}
      {operation && <p role="status">{operation.status} · {operation.phase ?? ""} · {operation.result_revision ?? operation.base_revision}. {active ? "Scene hiện tại được giữ đến khi dựng lại xong." : operation.error}</p>}
      {error && <p role="alert" className="text-rust">{error}</p>}
    </div>
    <iframe inert={Boolean(draft || active)} tabIndex={draft || active ? -1 : 0} ref={frame} src={src} title="SuperSplat chọn Gaussian nguồn" className="min-h-0 flex-1 border-0" style={{ pointerEvents: draft || active ? "none" : "auto" }} allow="fullscreen; clipboard-write" />
  </div>;
}
