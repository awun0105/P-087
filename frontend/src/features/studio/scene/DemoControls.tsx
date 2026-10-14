"use client";

import { Bookmark, BookmarkX, Clapperboard, History, Loader2, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/shadcn/dialog";
import { notifySuccess } from "@/components/studio/feedback";
import { Badge, Button, buttonVariants } from "@/components/studio/primitives";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useAuth } from "@/features/studio/AuthProvider";
import { canDecideReview, canEdit, isReviewer } from "@/lib/api/auth";
import { clearDemo, getDemoState, markDemo, publishDemo, resetDemo, restoreRoot } from "@/lib/api/studio";
import type { DemoState } from "@/lib/contracts/studio";
import { errorMessage } from "@/lib/ui-error";

/**
 * Hai việc khác nhau trên header scene, tách rõ để khỏi nhầm:
 *
 * - **Trạng thái đã lưu** (Reviewer lưu/bỏ): lưu revision hiện tại để sau khi chỉnh sửa có thể đưa scene
 *   về đúng lúc đó. Khôi phục tạo revision mới (lịch sử còn nguyên), không chạy lại bước xử lý nào.
 * - **Đặt làm bản demo** (chỉ Reviewer): xuất scene vào thư viện mẫu để mọi người xem ở `/new/try-demo`. Thư viện mẫu
 *   công khai nên hộp thoại đòi Reviewer xác nhận được công khai; backend còn kiểm lời khai quyền sử dụng và ẩn danh.
 *
 * `revision` là revision mới nhất màn hình biết; đổi thì đọc lại trạng thái để biết scene còn đúng mốc không.
 */
export function DemoControls({
  jobId,
  revision,
  sceneReady,
  defaultTitle = "",
  scope = "all",
  onRestored,
}: {
  jobId: string;
  revision: string | null;
  sceneReady: boolean;
  /** Tên scene, điền sẵn làm tên mẫu khi xuất. */
  defaultTitle?: string;
  scope?: "all" | "state" | "publication";
  /** Revision mới sau khi khôi phục; màn Studio dùng để tải lại scene. */
  onRestored: (revision: string) => void;
}) {
  const { me } = useAuth();
  const reviewer = isReviewer(me);
  const editable = canEdit(me);
  // Xuất vào thư viện công khai luôn cần phiên Reviewer thật (backend từ chối nếu tắt đăng nhập).
  const canPublish = canDecideReview(me);
  const [state, setState] = useState<DemoState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    if (!sceneReady) return;
    const controller = new AbortController();
    getDemoState(jobId, controller.signal).then(
      (next) => { if (!controller.signal.aborted) setState(next); },
      (cause: unknown) => { if (!controller.signal.aborted) setError(errorMessage(cause, "Không tải được trạng thái scene.")); },
    );
    return () => controller.abort();
  }, [jobId, revision, sceneReady]);

  const run = useCallback(async (action: () => Promise<DemoState>, success: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setState(next);
      notifySuccess(success);
      return next;
    } catch (cause) {
      setError(errorMessage(cause, "Thao tác bản demo thất bại"));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  if (!sceneReady) return null;
  if (!state) return scope === "state" ? <p role={error ? "alert" : "status"} className="text-sm text-on-dark/70">{error ?? "Đang tải trạng thái scene…"}</p> : null;
  const baseline = state.baseline;
  const publishedId = state.published_sample_id ?? null;
  const panel = scope === "state";
  const stateButton = panel ? "w-full justify-center border-line-dark text-on-dark hover:bg-on-dark/10" : undefined;
  if (scope === "publication" && !publishedId && !canPublish) return null;
  // Scene thường và người xem không phải Reviewer: không có gì về bản demo để hiện.
  if (!baseline && !publishedId && !editable) return null;
  async function restore() {
    if (!state?.current_revision) return;
    if (!window.confirm("Quay lại trạng thái đã lưu?")) return;
    const next = await run(() => resetDemo(jobId, state.current_revision!), "Đã quay lại trạng thái đã lưu.");
    if (next?.current_revision) onRestored(next.current_revision);
  }
  async function restoreOriginal() {
    if (!state?.current_revision) return;
    if (!window.confirm("Về bản gốc lúc scene được tạo xong? Trạng thái đã lưu vẫn được giữ để bạn quay lại.")) return;
    const next = await run(() => restoreRoot(jobId, state.current_revision!), "Đã khôi phục về bản gốc ban đầu.");
    if (next?.current_revision) onRestored(next.current_revision);
  }
  return (
    <div className={panel ? "space-y-5" : "flex flex-wrap items-center gap-2"}>
      {panel && <div className="space-y-1"><h3 className="label-tech text-on-dark/60">Trạng thái hiện tại</h3><p className="text-sm text-on-dark">{state.at_root ? "Đang ở bản gốc" : state.at_baseline ? "Đang ở trạng thái đã lưu" : "Scene đã được chỉnh sửa"}</p></div>}
      {scope !== "publication" && reviewer && (
        <div className={panel ? "space-y-2" : "contents"}>
        <Button size="sm" variant={panel ? "primary" : "ghost"} className={panel ? "w-full" : undefined} disabled={busy} onClick={() => void run(() => markDemo(jobId), "Đã lưu trạng thái scene hiện tại.")}
          title={baseline ? "Lưu scene hiện tại, thay thế trạng thái đã lưu trước đó." : "Lưu trạng thái hiện tại để quay lại về sau."}>
          <Bookmark aria-hidden />
          Lưu trạng thái
        </Button>
        {panel && <p className="text-xs text-on-dark/60">{baseline ? "Lưu lại sẽ thay thế trạng thái đã lưu trước đó." : "Lưu scene hiện tại để quay lại sau."}</p>}
        </div>
      )}
      {scope !== "publication" && <div className={panel ? "space-y-3" : "contents"}>
      {panel ? <>
        <h3 className="label-tech text-on-dark/60">Trạng thái đã lưu</h3>
        {baseline ? <div className="space-y-1 text-xs text-on-dark/70"><p>Đã lưu lúc <time dateTime={baseline.marked_at}>{new Date(baseline.marked_at).toLocaleString("vi-VN")}</time></p>{baseline.marked_by && <p>Bởi {baseline.marked_by.display_name}</p>}</div> : <p className="text-sm text-on-dark/60">Chưa có trạng thái đã lưu.</p>}
      </> : baseline && <Badge tone="neutral" title={`Trạng thái đã lưu: ${baseline.scene_revision}`}>Có trạng thái đã lưu</Badge>}
      {(baseline || panel) && editable && (
        <Button size="sm" variant="secondary" className={panel ? `${stateButton} bg-on-dark/10` : undefined} disabled={busy || !baseline || state.at_baseline} onClick={() => void restore()}
          title={state.at_baseline ? "Scene đang ở trạng thái đã lưu." : "Đưa scene về trạng thái bạn đã lưu."}>
          <RotateCcw aria-hidden />
          Quay lại trạng thái đã lưu
        </Button>
      )}
      {reviewer && baseline && (
        <Button size="sm" variant="ghost" className={panel ? "h-auto px-0 text-xs text-on-dark/60 hover:text-rust hover:bg-transparent" : undefined} disabled={busy}
          onClick={() => { if (window.confirm("Bỏ trạng thái đã lưu?")) void run(() => clearDemo(jobId), "Đã bỏ trạng thái đã lưu."); }}>
          <BookmarkX aria-hidden />
          Bỏ trạng thái đã lưu
        </Button>
      )}
      </div>}
      {scope !== "publication" && editable && (
        <div className={panel ? "space-y-3 border-t border-line-dark pt-4" : "contents"}>
        {panel && <><h3 className="label-tech text-on-dark/60">Bản gốc</h3><p className="text-xs text-on-dark/60">Kết quả ban đầu của pipeline. Trạng thái đã lưu vẫn được giữ khi về bản gốc.</p></>}
        <Button size="sm" variant="ghost" className={stateButton} disabled={busy || Boolean(state.at_root)} onClick={() => void restoreOriginal()}
          title={state.at_root ? "Scene đang ở bản gốc ban đầu." : "Về bản gốc lúc scene được tạo xong; giữ nguyên trạng thái đã lưu."}>
          <History aria-hidden />
          Về bản gốc
        </Button>
        </div>
      )}
      {scope !== "state" && (publishedId ? (
        <Link href={`/new/try-demo?sample=${encodeURIComponent(publishedId)}`} className={buttonVariants({ size: "sm", variant: "secondary" })}>
          <Clapperboard aria-hidden />
          Đã có trong thư viện mẫu
        </Link>
      ) : canPublish ? (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPublishing(true)}
          title="Xuất scene này vào thư viện mẫu để mọi người xem ở Thử mẫu.">
          <Clapperboard aria-hidden />
          Đặt làm bản demo
        </Button>
      ) : null)}
      {error && <span role="alert" className="text-xs text-rust">{error}</span>}
      {scope !== "state" && canPublish && (
        <PublishDialog
          open={publishing}
          onOpenChange={setPublishing}
          jobId={jobId}
          defaultTitle={defaultTitle}
          onPublished={(sampleId) => {
            setState((current) => (current ? { ...current, published_sample_id: sampleId } : current));
            notifySuccess("Đã xuất vào thư viện mẫu.");
          }}
          // Lỗi "đã có trong thư viện" (người khác vừa xuất): đọc lại trạng thái để nút đổi sang đường dẫn tới mẫu.
          onFailed={() => {
            void getDemoState(jobId).then((next) => setState(next), () => undefined);
          }}
        />
      )}
    </div>
  );
}

function PublishDialog({ open, onOpenChange, jobId, defaultTitle, onPublished, onFailed }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: string;
  defaultTitle: string;
  onPublished: (sampleId: string) => void;
  onFailed: () => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!submitting) onOpenChange(next); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Đặt làm bản demo</DialogTitle>
          <DialogDescription>
            Xuất scene này vào thư viện mẫu. Mọi người xem được ở “Thử mẫu”, kể cả khi chưa đăng nhập, gồm video gốc và các
            khung hình của scene.
          </DialogDescription>
        </DialogHeader>
        {/* Form chỉ được dựng khi hộp thoại mở: mỗi lần mở là một form mới với tên scene hiện tại. */}
        <PublishForm
          jobId={jobId}
          defaultTitle={defaultTitle}
          onSubmitting={setSubmitting}
          onCancel={() => onOpenChange(false)}
          onPublished={(sampleId) => { onPublished(sampleId); onOpenChange(false); }}
          onFailed={onFailed}
        />
      </DialogContent>
    </Dialog>
  );
}

function PublishForm({ jobId, defaultTitle, onSubmitting, onCancel, onPublished, onFailed }: {
  jobId: string;
  defaultTitle: string;
  onSubmitting: (submitting: boolean) => void;
  onCancel: () => void;
  onPublished: (sampleId: string) => void;
  onFailed: () => void;
}) {
  const ids = { title: useId(), description: useId() };
  const [title, setTitle] = useState(defaultTitle);
  const [description, setDescription] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    onSubmitting(true);
    setError(null);
    try {
      const result = await publishDemo(jobId, { title: title.trim() || undefined, description: description.trim(), confirm_public: confirmed });
      onPublished(result.sample_id);
    } catch (cause) {
      setError(errorMessage(cause, "Không xuất được vào thư viện mẫu"));
      onFailed();
    } finally {
      setSubmitting(false);
      onSubmitting(false);
    }
  }

  return (
    <>
      <div className="space-y-4 text-sm">
        <div>
          <label htmlFor={ids.title} className="font-medium">Tên mẫu</label>
          <input id={ids.title} value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200}
            className="mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30" />
        </div>
        <div>
          <label htmlFor={ids.description} className="font-medium">Mô tả (tuỳ chọn)</label>
          <textarea id={ids.description} value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1000} rows={3}
            className="mt-1.5 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 py-2 outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30" />
        </div>
        <label className="flex cursor-pointer items-start gap-3">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 size-4 shrink-0 accent-ember-strong" />
          <span>Tôi xác nhận video và kết quả của scene này được phép công khai.</span>
        </label>
        {error && <p role="alert" className="text-rust">{error}</p>}
      </div>
      <DialogFooter>
        <Button variant="ghost" disabled={submitting} onClick={onCancel}>Huỷ</Button>
        <Button disabled={!confirmed || submitting} onClick={() => void submit()}>
          {submitting ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <Clapperboard aria-hidden />}
          {submitting ? "Đang xuất…" : "Xuất vào thư viện mẫu"}
        </Button>
      </DialogFooter>
    </>
  );
}
