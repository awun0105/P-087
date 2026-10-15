"use client";

import { Button, Notice } from "@/components/studio/primitives";
import { useObjectify } from "@/features/studio/scene/objectifyContext";
import type { SceneIR } from "@/lib/contracts/api";
import { objectGeometryState } from "@/lib/scene/geometry-state";

/** Vật đã xoá, gộp hoặc loại không còn trong scene để dựng mesh. */
const ARCHIVED_REVIEW = new Set(["DELETED", "MERGED", "IGNORED"]);

/**
 * Banner trên viewport khi scene là Draft: báo số vật còn giữ và chưa có collider, nút **Tạo mesh** chạy một lần.
 * Vật có lỗi vỏ được cảnh báo để người dùng sửa vùng trước; nút vẫn bấm được, máy chủ sẽ báo lỗi rõ.
 */
export function GeometryReviewBanner({ jobId, scene, onRevision }: { jobId: string; scene: SceneIR; onRevision: () => void }) {
  const { error, sending, pending, send } = useObjectify({ jobId, revision: scene.scene_revision, onRevision });
  if (objectGeometryState(scene) !== "awaiting_review") return null;
  const kept = scene.objects.filter((item) => !ARCHIVED_REVIEW.has(String(item.provenance.review)));
  // Builder dựng vỏ cho mọi vật có nhãn trong membership, kể cả vật đã loại, và từ chối khi vỏ lỗi: nên nêu đủ các vật này.
  const owners = new Set(Object.values(scene.environment.membership?.label_to_object_id ?? {}));
  const shellErrors = scene.objects.filter(
    (item) => owners.has(item.id) && typeof item.provenance.shell_error === "string",
  );
  return (
    <section aria-label="Duyệt tách vật" className="m-3">
      <Notice tone="ember">
        <p className="font-medium">Đang duyệt tách vật · {kept.length} vật · chưa có collider</p>
        <p className="mt-1 text-xs opacity-80">Chỉnh vùng từng vật nếu cần, rồi Tạo mesh. Bước này chạy một lần.</p>
        {shellErrors.map((item) => {
          const archived = ARCHIVED_REVIEW.has(String(item.provenance.review)) || ARCHIVED_REVIEW.has(String(item.state));
          return (
            <p key={item.id} className="mt-1 text-xs text-rust">
              {archived
                ? `Vỏ của ${item.name} (đã loại) chưa dựng được — Khôi phục, sửa vùng, rồi Tạo mesh`
                : `Vỏ của ${item.name} chưa dựng được — sửa vùng trước khi Tạo mesh`}
            </p>
          );
        })}
        <span className="mt-2 flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={sending || pending} onClick={() => void send("geometry", scene.scene_revision)}>
            {shellErrors.length > 0 && <span className="size-2 rounded-full bg-rust" aria-hidden />}
            Tạo mesh
          </Button>
        </span>
        {error && <span className="mt-1 block text-xs">{error}</span>}
      </Notice>
    </section>
  );
}
