"use client";

import { useEffect, useState, type RefObject } from "react";

import { Loader2 } from "lucide-react";
import { Button, Notice } from "@/components/studio/primitives";
import { toCommandBoxes, validateBoxes } from "@/features/studio/region/box-model";
import {
  addAddBox,
  addSubtractBox,
  boxLabel,
  canRemoveBox,
  initialRegionSession,
  removeRegionBox,
  selectRegionBox,
  setRegionClaim,
  type RegionSession,
  type RegionViewApi,
} from "@/features/studio/region/region-session";
import { useRegionPreview } from "@/features/studio/region/useRegionPreview";
import type { ViewPreset } from "@/features/viewer/region-overlay";
import { ApiError } from "@/lib/api/client";
import { applyObjectRegion } from "@/lib/api/studio";
import type { SceneObject } from "@/lib/contracts/api";

const VIEWS: { preset: ViewPreset; label: string }[] = [
  { preset: "top", label: "Trên" },
  { preset: "front", label: "Trước" },
  { preset: "side", label: "Cạnh" },
];

const NOT_READY_VIEW = "Góc nhìn chưa sẵn sàng: viewer chưa nối lệnh chuyển camera.";

/** Kết quả Apply: 201 trên Draft (scene mới) hoặc 202 trên Ready (đang dựng lại vật). */
type ApplyResult = Awaited<ReturnType<typeof applyObjectRegion>>;

/** Phím Delete đang gõ trong ô nhập thì không được xoá box. */
function isTextField(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
}

/**
 * Panel chỉnh vùng một vật: danh sách box cộng/trừ, thêm và xoá box, góc nhìn, và kết quả xem trước (bộ đếm, vật
 * chồng lấn, cảnh báo vỏ). Phiên nằm ở cha và được đổi qua `onSession`, nên viewport và panel luôn đọc cùng một
 * danh sách box.
 */
export function RegionEditor({
  jobId,
  object,
  sceneRevision,
  membershipChecksum,
  nameOf,
  session,
  onSession,
  onApplied,
  onReload,
  onClose,
  viewApi,
}: {
  jobId: string;
  object: SceneObject;
  /** Revision của scene khi mở panel: máy chủ từ chối (409) nếu scene đã đổi. */
  sceneRevision: string;
  /** Checksum membership đang dùng: máy chủ từ chối (409) nếu membership đã đổi. */
  membershipChecksum: string;
  /** Tên hiển thị của một vật theo id, để nêu tên vật chồng lấn. */
  nameOf(id: string): string;
  session: RegionSession;
  onSession(next: RegionSession): void;
  /** Máy chủ đã nhận Apply: cha đóng panel và tải lại theo kết quả (201 scene mới, 202 đang dựng lại). */
  onApplied(result: ApplyResult): void;
  /** Tải lại scene sau xung đột (409); box trong panel được giữ nguyên. */
  onReload(): void;
  onClose(): void;
  /** Cầu nối tới overlay vùng trong viewer; null khi viewer chưa sẵn sàng. */
  viewApi: RefObject<RegionViewApi | null>;
}) {
  // Góc nhìn chưa nối là trạng thái thật của viewer: sau lần đầu trả false thì khoá các nút góc nhìn.
  const [viewsReady, setViewsReady] = useState(true);
  const boxError = validateBoxes(session.boxes);
  const region = useRegionPreview({
    jobId,
    objectId: object.id,
    expectedRevision: sceneRevision,
    membershipChecksum,
    boxes: session.boxes,
    claimFrom: session.claimFrom,
    enabled: boxError === null,
  });
  // Kết quả chỉ có khi khớp box hiện tại; đổi box thì bộ đếm cũ ẩn đi trong lúc tính lại.
  const preview = region.preview;
  const overlaps = preview ? Object.entries(preview.overlaps).filter(([, count]) => count > 0) : [];
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  // Apply chỉ bật khi có xem trước khớp box hiện tại và box hợp lệ; đổi box là tắt lại tới khi xem trước mới về.
  const canApply = preview !== null && boxError === null && !applying;

  async function apply() {
    if (!canApply) return;
    setApplying(true);
    setApplyError(null);
    setConflict(false);
    try {
      const result = await applyObjectRegion(jobId, object.id, {
        expected_scene_revision: sceneRevision,
        membership_checksum: membershipChecksum,
        boxes: toCommandBoxes(session.boxes),
        claim_from: [...session.claimFrom],
      });
      onApplied(result);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) setConflict(true);
      else setApplyError(cause instanceof ApiError ? cause.detail : "Không áp dụng được vùng.");
    } finally {
      setApplying(false);
    }
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Delete") {
        if (!isTextField(event.target) && session.selectedId && canRemoveBox(session, session.selectedId)) {
          onSession(removeRegionBox(session, session.selectedId));
        }
        return;
      }
      // Khi đang kéo tay nắm, Esc thuộc về overlay (huỷ kéo); chỉ đóng panel khi không kéo.
      if (event.key === "Escape" && !viewApi.current?.isGesturing()) onClose();
    }
    // Pha bắt: đọc trạng thái kéo trước khi overlay nhận Esc và huỷ cử chỉ, không phụ thuộc thứ tự đăng ký.
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [session, onSession, onClose, viewApi]);

  function look(preset: ViewPreset) {
    const moved = viewApi.current?.viewFrom(preset) ?? false;
    if (!moved) setViewsReady(false);
  }

  return (
    <section
      aria-label="Chỉnh vùng"
      className="pointer-events-auto w-80 max-w-full space-y-3 rounded-md border border-line-dark bg-viewport-deep/95 p-3 text-xs text-on-dark shadow-2xl backdrop-blur-md"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 className="truncate text-sm font-semibold">Chỉnh vùng · {object.name}</h3>
        <button
          type="button"
          aria-label="Đóng chỉnh vùng"
          onClick={onClose}
          className="rounded p-1 text-on-dark/70 hover:bg-on-dark/10 hover:text-on-dark"
        >
          ×
        </button>
      </header>

      <ul aria-label="Box vùng" className="space-y-1">
        {session.boxes.map((box, index) => {
          const label = boxLabel(box, index);
          const removable = canRemoveBox(session, box.id);
          const selected = box.id === session.selectedId;
          return (
            <li key={box.id} className="flex items-center gap-1">
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onSession(selectRegionBox(session, box.id))}
                className={`flex-1 rounded px-2 py-1 text-left ${selected ? "bg-ember-soft text-ember-strong font-medium" : "hover:bg-on-dark/10"}`}
              >
                {label}
              </button>
              <button
                type="button"
                aria-label={`Xoá ${label}`}
                disabled={!removable}
                title={removable ? "Xoá box" : "Không xoá box cộng cuối cùng"}
                onClick={() => onSession(removeRegionBox(session, box.id))}
                className="rounded px-2 py-1 hover:bg-on-dark/10 disabled:cursor-not-allowed disabled:opacity-40"
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => onSession(addAddBox(session))}>
          + Box cộng
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onSession(addSubtractBox(session))}>
          − Box trừ
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            const initial = initialRegionSession(object);
            if (initial) onSession(initial);
          }}
        >
          Đặt lại
        </Button>
      </div>

      <div role="group" aria-label="Góc nhìn" className="flex flex-wrap gap-2">
        {VIEWS.map(({ preset, label }) => (
          <Button
            key={preset}
            size="sm"
            variant="ghost"
            disabled={!viewsReady || !session.selectedId}
            title={viewsReady ? undefined : NOT_READY_VIEW}
            onClick={() => look(preset)}
          >
            {label}
          </Button>
        ))}
      </div>

      <div aria-live="polite" className="space-y-2">
        {region.loading && (
          <p className="flex items-center gap-2 text-on-dark/70">
            <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> Đang tính vùng…
          </p>
        )}
        {preview && (
          <div className="space-y-1">
            <p className="font-medium">
              +{preview.added_count} / −{preview.removed_count} · tổng {preview.object_gaussian_count}
            </p>
            <p className="text-on-dark/70">Bảo vệ sàn: {preview.protected_floor_count}</p>
          </div>
        )}
        {overlaps.length > 0 && (
          <ul aria-label="Vật chồng lấn" className="space-y-2">
            {overlaps.map(([id, count]) => {
              const name = nameOf(id);
              const claimed = session.claimFrom.includes(id);
              return (
                <li key={id} className="space-y-1 rounded border border-line-dark p-2">
                  <p>
                    Box chồng lên {name} ({count} Gaussian) — {claimed ? "sẽ lấy về vật này" : "giữ chủ cũ"}
                  </p>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      aria-label={`Lấy luôn từ ${name}`}
                      checked={claimed}
                      onChange={(event) => onSession(setRegionClaim(session, id, event.target.checked))}
                    />
                    Lấy luôn
                  </label>
                </li>
              );
            })}
          </ul>
        )}
        {preview?.shell_error && (
          <Notice tone="ochre">
            Vỏ chưa dựng được: {preview.shell_error}. Apply vẫn được nhưng Tạo mesh sẽ báo lỗi cho vật này.
          </Notice>
        )}
      </div>

      {region.error && (
        <p role="alert" className="text-rust">
          {region.error}
        </p>
      )}
      {boxError && (
        <p role="alert" className="text-rust">
          {boxError}
        </p>
      )}
      {conflict && (
        <div role="alert" className="space-y-2 text-rust">
          <p>Scene đã đổi ở lượt khác. Tải lại để chỉnh tiếp.</p>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setConflict(false);
              onReload();
            }}
          >
            Tải lại
          </Button>
        </div>
      )}
      {applyError && (
        <p role="alert" className="text-rust">
          {applyError}
        </p>
      )}

      <div className="flex justify-end gap-2 border-t border-line-dark pt-3">
        <Button size="sm" variant="ghost" onClick={onClose}>
          Huỷ
        </Button>
        <Button size="sm" disabled={!canApply} onClick={() => void apply()}>
          {applying && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
          Apply
        </Button>
      </div>
    </section>
  );
}
