"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";

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
import { notifySuccess } from "@/components/studio/feedback";
import { Button } from "@/components/studio/primitives";
import { cn } from "@/lib/cn";
import { errorMessage } from "@/lib/ui-error";

/**
 * Nút chuyển một scene vào thùng rác, có bước xác nhận. Lỗi từ backend (scene đang được xử lý, đã phát hành…) hiện ngay
 * trong hộp thoại; thành công thì gọi `onMoved` để danh sách tải lại.
 */
export function MoveToTrashButton({ name, move, onMoved, className }: {
  name: string;
  move: () => Promise<unknown>;
  onMoved: () => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true); setError(null);
    try {
      await move();
      setOpen(false);
      notifySuccess(`Đã chuyển “${name}” vào thùng rác`);
      onMoved();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        className={cn("size-8 px-0", className)}
        aria-label={`Chuyển ${name} vào thùng rác`}
        title="Chuyển vào thùng rác"
        onClick={() => { setError(null); setOpen(true); }}
      >
        <Trash2 aria-hidden />
      </Button>
      <AlertDialog open={open} onOpenChange={(value) => { if (!busy) setOpen(value); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Chuyển “{name}” vào thùng rác?</AlertDialogTitle>
            <AlertDialogDescription>
              Scene biến khỏi danh sách nhưng vẫn khôi phục được từ trang Thùng rác cho tới khi bị xoá hẳn.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && <p role="alert" className="rounded-lg border border-rust/30 bg-rust-soft p-3 text-sm text-rust">{error}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Giữ lại</AlertDialogCancel>
            <AlertDialogAction disabled={busy} onClick={(event) => { event.preventDefault(); void confirm(); }}>
              {busy ? "Đang chuyển…" : "Chuyển vào thùng rác"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
