"use client";

import { Button } from "@/components/studio/primitives";
import { useObjectify } from "@/features/studio/scene/objectifyContext";
import type { SceneIR } from "@/lib/contracts/api";
import { objectGeometryState } from "@/lib/scene/geometry-state";

/** Vật đã xoá, gộp hoặc loại không còn trong scene để dựng mesh. */
const ARCHIVED_REVIEW = new Set(["DELETED", "MERGED", "IGNORED"]);

/** Nút tạo mesh trong panel vật thể của scene Draft. */
export function GeometryReviewBanner({ jobId, scene, onRevision, busy = false }: { jobId: string; scene: SceneIR; onRevision: () => void; busy?: boolean }) {
  const { error, sending, pending, send } = useObjectify({ jobId, revision: scene.scene_revision, onRevision });
  if (objectGeometryState(scene) !== "awaiting_review") return null;
  const kept = scene.objects.filter((item) => !ARCHIVED_REVIEW.has(String(item.provenance.review)));
  const pendingReview = kept.filter((item) => item.state === "CANDIDATE");
  const chosen = kept.filter((item) => item.state === "CONFIRMED");
  return (
    <section aria-label="Tạo mesh vật thể" className="px-3 py-2">
      <Button size="sm" disabled={busy || sending || pending || pendingReview.length > 0} onClick={() => void send("geometry", scene.scene_revision)}>
        Tạo mesh cho {chosen.length} vật đã chọn
      </Button>
      {pendingReview.length > 0 && <p className="mt-1 text-xs">Duyệt các vật còn lại trước khi tạo mesh.</p>}
      {error && <span className="mt-1 block text-xs">{error}</span>}
    </section>
  );
}
