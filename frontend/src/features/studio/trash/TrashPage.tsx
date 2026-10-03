"use client";

import { RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/shadcn/alert-dialog";
import { Checkbox } from "@/components/shadcn/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/shadcn/table";
import { ErrorFeedback, notifySuccess, PageHeader } from "@/components/studio/feedback";
import { Button, EmptyState, Notice } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { canEdit, isReviewer } from "@/lib/api/auth";
import { listTrash, purgeTrash, restoreTrash, type TrashActionResult, type TrashEntry } from "@/lib/api/studio";
import { formatBytes } from "@/lib/format";
import { errorMessage } from "@/lib/ui-error";

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" });
const KIND_LABEL = { scene: "Scene", import: "Scene nhập", upload: "File nguồn" } as const;
const DAY_MS = 24 * 60 * 60 * 1000;

/** "Còn N ngày" trước khi mục tự bị xoá hẳn; làm tròn lên để ngày cuối vẫn hiện "Còn 1 ngày". */
export function remainingLabel(expiresAt: string | null, now: number): string {
  if (!expiresAt) return "Không tự xoá";
  const days = Math.ceil((Date.parse(expiresAt) - now) / DAY_MS);
  return days <= 0 ? "Sắp bị xoá hẳn" : `Còn ${days} ngày`;
}

/**
 * Trang Thùng rác (STUDIO_UX_SPEC.md D-15): scene đã gỡ nằm ở đây tới khi được khôi phục hoặc xoá hẳn. Chọn từng mục,
 * nhiều mục hoặc tất cả. Xoá hẳn không hoàn tác được (xoá cả file trên kho) nên luôn qua bước xác nhận và chỉ Reviewer
 * làm được; backend vẫn kiểm quyền.
 */
export function TrashPage() {
  const { me } = useAuth();
  const allowed = canEdit(me);
  const mayPurge = isReviewer(me);
  const [entries, setEntries] = useState<TrashEntry[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [failures, setFailures] = useState<TrashActionResult["failed"]>([]);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<string[] | null>(null);
  // Mốc "bây giờ" lấy lúc tải danh sách: render phải thuần, không gọi Date.now() trong thân component.
  const [loadedAt, setLoadedAt] = useState(0);

  const load = useCallback(async () => {
    try {
      const next = await listTrash();
      setEntries(next);
      setLoadedAt(Date.now());
      // Mục đã bị xử lý ở tab khác thì không còn được chọn.
      setSelected((current) => new Set(next.map((entry) => entry.entry_id).filter((id) => current.has(id))));
      setError(null);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }, []);

  useEffect(() => {
    if (!allowed) return;
    // Tải sau khi effect chạy xong: không setState đồng bộ trong thân effect.
    const timer = setTimeout(() => { void load(); }, 0);
    return () => clearTimeout(timer);
  }, [allowed, load]);

  async function run(action: "restore" | "purge", ids: string[]) {
    if (ids.length === 0) return;
    setBusy(true); setFailures([]); setError(null);
    try {
      const result = await (action === "restore" ? restoreTrash(ids) : purgeTrash(ids));
      setFailures(result.failed);
      if (result.done.length > 0) {
        notifySuccess(action === "restore" ? `Đã khôi phục ${result.done.length} mục` : `Đã xoá hẳn ${result.done.length} mục`);
      }
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
      await load();
    }
  }

  if (me === null) return <main className="mx-auto max-w-5xl px-4 pt-10 sm:px-6"><p role="status" className="text-sm text-ink-muted">Đang kiểm tra quyền truy cập…</p></main>;
  if (!allowed) {
    return <main className="mx-auto max-w-5xl px-4 pt-10 sm:px-6"><EmptyState icon={<Trash2 aria-hidden />} title="Đăng nhập để xem thùng rác">Thùng rác chỉ dành cho thành viên của nhóm.</EmptyState></main>;
  }

  const all = entries?.map((entry) => entry.entry_id) ?? [];
  const chosen = all.filter((id) => selected.has(id));
  const everything = all.length > 0 && chosen.length === all.length;
  const toggle = (id: string, on: boolean) => setSelected((current) => {
    const next = new Set(current);
    if (on) next.add(id); else next.delete(id);
    return next;
  });
  const nameOf = (id: string) => entries?.find((entry) => entry.entry_id === id)?.title ?? id;

  return (
    <main className="mx-auto max-w-5xl px-4 pt-10 pb-20 sm:px-6">
      <PageHeader
        title="Thùng rác"
        description="Scene đã gỡ nằm ở đây tới hạn ở cột “Tự xoá” rồi bị xoá hẳn; trước hạn đó bạn khôi phục hoặc xoá hẳn được. Xoá hẳn sẽ xoá cả file trên kho lưu trữ và không khôi phục được."
        action={all.length > 0 ? (
          <>
            <Button variant="secondary" disabled={busy} onClick={() => void run("restore", all)}><RotateCcw aria-hidden /> Khôi phục tất cả</Button>
            <Button variant="danger" disabled={busy || !mayPurge} onClick={() => setConfirming(all)}><Trash2 aria-hidden /> Xoá tất cả</Button>
          </>
        ) : undefined}
      />
      {!mayPurge && all.length > 0 && <Notice tone="neutral" className="mt-6">Chỉ Reviewer xoá hẳn được. Bạn vẫn khôi phục được các mục trong thùng rác.</Notice>}
      {error && <ErrorFeedback className="mt-6" message={error} retry={() => void load()} />}
      {failures.length > 0 && (
        <Notice tone="rust" className="mt-6">
          <p className="font-medium">{failures.length} mục chưa xử lý được:</p>
          <ul className="mt-1 list-disc pl-5">
            {failures.map((failure) => <li key={failure.entry_id}>{nameOf(failure.entry_id)}: {failure.reason}</li>)}
          </ul>
        </Notice>
      )}
      {entries === null && !error && <p role="status" className="mt-8 text-sm text-ink-muted">Đang tải thùng rác…</p>}
      {entries?.length === 0 && (
        <div className="mt-8"><EmptyState icon={<Trash2 aria-hidden />} title="Thùng rác trống">Scene bạn gỡ từ trang Scenes sẽ xuất hiện ở đây.</EmptyState></div>
      )}
      {entries && entries.length > 0 && (
        <>
          <div className="mt-8 flex min-h-10 flex-wrap items-center gap-2 text-sm text-ink-muted" aria-live="polite">
            <span>{chosen.length > 0 ? `Đã chọn ${chosen.length}/${all.length} mục` : `${all.length} mục`}</span>
            {chosen.length > 0 && (
              <>
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("restore", chosen)}><RotateCcw aria-hidden /> Khôi phục mục đã chọn</Button>
                <Button size="sm" variant="danger" disabled={busy || !mayPurge} onClick={() => setConfirming(chosen)}><Trash2 aria-hidden /> Xoá hẳn mục đã chọn</Button>
              </>
            )}
          </div>
          <div className="mt-3 overflow-hidden rounded-xl border border-line">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox checked={everything} onCheckedChange={(value) => setSelected(new Set(value === true ? all : []))} aria-label="Chọn tất cả" />
                  </TableHead>
                  <TableHead>Tên</TableHead>
                  <TableHead className="hidden sm:table-cell">Gỡ lúc</TableHead>
                  <TableHead>Tự xoá</TableHead>
                  <TableHead className="hidden md:table-cell">Dung lượng</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry) => (
                  <TableRow key={entry.entry_id} data-state={selected.has(entry.entry_id) ? "selected" : undefined}>
                    <TableCell>
                      <Checkbox checked={selected.has(entry.entry_id)} onCheckedChange={(value) => toggle(entry.entry_id, value === true)} aria-label={`Chọn ${entry.title}`} />
                    </TableCell>
                    <TableCell className="max-w-72">
                      <p className="truncate font-medium text-ink">{entry.title}</p>
                      <p className="truncate text-xs text-ink-subtle">
                        {entry.items.map((item) => `${KIND_LABEL[item.kind]}${item.kind === "upload" ? ` ${item.name}` : ""}`).join(" · ")}
                      </p>
                    </TableCell>
                    <TableCell className="hidden text-xs value-tech text-ink-muted sm:table-cell">{DATE.format(new Date(entry.deleted_at))}</TableCell>
                    <TableCell className="text-xs whitespace-nowrap value-tech text-ink-muted">{remainingLabel(entry.expires_at, loadedAt)}</TableCell>
                    <TableCell className="hidden text-xs value-tech text-ink-muted md:table-cell">{formatBytes(entry.size_bytes)}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("restore", [entry.entry_id])} aria-label={`Khôi phục ${entry.title}`}>
                          <RotateCcw aria-hidden /> <span className="hidden lg:inline">Khôi phục</span>
                        </Button>
                        <Button size="sm" variant="danger" disabled={busy || !mayPurge} onClick={() => setConfirming([entry.entry_id])} aria-label={`Xoá hẳn ${entry.title}`}>
                          <Trash2 aria-hidden /> <span className="hidden lg:inline">Xoá hẳn</span>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
      <AlertDialog open={confirming !== null} onOpenChange={(value) => { if (!value) setConfirming(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirming?.length === 1 ? `Xoá hẳn “${nameOf(confirming[0])}”?` : `Xoá hẳn ${confirming?.length ?? 0} mục?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              Toàn bộ dữ liệu và file của các scene này bị xoá khỏi máy chủ và kho lưu trữ. Thao tác này không khôi phục được.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Giữ lại</AlertDialogCancel>
            <AlertDialogAction onClick={() => { const ids = confirming ?? []; setConfirming(null); void run("purge", ids); }}>
              Xoá hẳn
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}
