"use client";

import { Bookmark, BookmarkX, Clapperboard, Loader2, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/shadcn/dialog";
import { notifySuccess } from "@/components/studio/feedback";
import { Badge, Button, buttonVariants } from "@/components/studio/primitives";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useAuth } from "@/features/studio/AuthProvider";
import { isReviewer } from "@/lib/api/auth";
import { clearDemo, getDemoState, markDemo, publishDemo, resetDemo } from "@/lib/api/studio";
import type { DemoState } from "@/lib/contracts/studio";
import { errorMessage } from "@/lib/ui-error";

/**
 * Hai việc khác nhau trên header scene, tách rõ để khỏi nhầm:
 *
 * - **Mốc gốc** (ai cũng khôi phục được, Reviewer đặt/bỏ): lưu revision hiện tại để sau khi chỉnh sửa có thể đưa scene
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
  onRestored,
}: {
  jobId: string;
  revision: string | null;
  sceneReady: boolean;
  /** Tên scene, điền sẵn làm tên mẫu khi xuất. */
  defaultTitle?: string;
  /** Revision mới sau khi khôi phục; màn Studio dùng để tải lại scene. */
  onRestored: (revision: string) => void;
}) {
  const { me } = useAuth();
  const reviewer = isReviewer(me);
  const [state, setState] = useState<DemoState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    if (!sceneReady) return;
    const controller = new AbortController();
    getDemoState(jobId, controller.signal).then(
      (next) => { if (!controller.signal.aborted) setState(next); },
      () => { /* Không đọc được trạng thái demo không chặn màn scene; chỉ ẩn điều khiển. */ },
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

  if (!sceneReady || !state) return null;
  const baseline = state.baseline;
  const publishedId = state.published_sample_id ?? null;
  // Scene thường và người xem không phải Reviewer: không có gì về bản demo để hiện.
  if (!baseline && !publishedId && !reviewer) return null;
  async function restore() {
    if (!state?.current_revision) return;
    if (!window.confirm("Đưa scene về mốc gốc? Mọi chỉnh sửa sau mốc gốc vẫn nằm trong lịch sử revision; không bước xử lý nào chạy lại.")) return;
    const next = await run(() => resetDemo(jobId, state.current_revision!), "Đã khôi phục về mốc gốc.");
    if (next?.current_revision) onRestored(next.current_revision);
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      {baseline && <Badge tone="neutral" title={`Mốc gốc: ${baseline.scene_revision}`}>Có mốc gốc</Badge>}
      {baseline && (
        <Button size="sm" variant="secondary" disabled={busy || state.at_baseline} onClick={() => void restore()}
          title={state.at_baseline ? "Scene đang đúng mốc gốc." : "Đưa scene về đúng lúc được đặt mốc gốc."}>
          <RotateCcw aria-hidden />
          {state.at_baseline ? "Đang ở mốc gốc" : "Khôi phục về mốc gốc"}
        </Button>
      )}
      {reviewer && !baseline && (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => markDemo(jobId), "Đã đặt mốc gốc cho scene.")}
          title="Lưu trạng thái hiện tại của scene làm mốc để khôi phục về sau.">
          <Bookmark aria-hidden />
          Đặt mốc gốc
        </Button>
      )}
      {reviewer && baseline && (
        <Button size="sm" variant="ghost" disabled={busy}
          onClick={() => { if (window.confirm("Bỏ mốc gốc? Nội dung scene giữ nguyên.")) void run(() => clearDemo(jobId), "Đã bỏ mốc gốc."); }}>
          <BookmarkX aria-hidden />
          Bỏ mốc gốc
        </Button>
      )}
      {publishedId ? (
        <Link href={`/new/try-demo?sample=${encodeURIComponent(publishedId)}`} className={buttonVariants({ size: "sm", variant: "secondary" })}>
          <Clapperboard aria-hidden />
          Đã có trong thư viện mẫu
        </Link>
      ) : reviewer ? (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPublishing(true)}
          title="Xuất scene này vào thư viện mẫu để mọi người xem ở Thử mẫu.">
          <Clapperboard aria-hidden />
          Đặt làm bản demo
        </Button>
      ) : null}
      {error && <span role="alert" className="text-xs text-rust">{error}</span>}
      {reviewer && (
        <PublishDialog
          open={publishing}
          onOpenChange={setPublishing}
          jobId={jobId}
          defaultTitle={defaultTitle}
          onPublished={(sampleId) => {
            setState((current) => (current ? { ...current, published_sample_id: sampleId } : current));
            notifySuccess("Đã xuất vào thư viện mẫu.");
          }}
        />
      )}
    </div>
  );
}

function PublishDialog({ open, onOpenChange, jobId, defaultTitle, onPublished }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: string;
  defaultTitle: string;
  onPublished: (sampleId: string) => void;
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
        />
      </DialogContent>
    </Dialog>
  );
}

function PublishForm({ jobId, defaultTitle, onSubmitting, onCancel, onPublished }: {
  jobId: string;
  defaultTitle: string;
  onSubmitting: (submitting: boolean) => void;
  onCancel: () => void;
  onPublished: (sampleId: string) => void;
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
