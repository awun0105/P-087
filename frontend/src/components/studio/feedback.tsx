"use client";

import { Check, CheckCircle2, CircleHelp, Copy, X } from "lucide-react";
import { Toast } from "radix-ui";
import { useEffect, useState, type ReactNode } from "react";

import { Button, Notice } from "@/components/studio/primitives";

const EVENT = "studio:feedback";
interface Feedback { id: number; message: string; key?: string }
let sequence = 0;

/** Chỉ gọi sau response thành công; host sống xuyên qua điều hướng Studio. */
export function notifySuccess(message: string, key?: string): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent<Feedback>(EVENT, { detail: { id: ++sequence, message, key } }));
}

export function FeedbackHost() {
  const [items, setItems] = useState<Feedback[]>([]);
  useEffect(() => {
    const receive = (event: Event) => {
      const item = (event as CustomEvent<Feedback>).detail;
      setItems((current) => [...current.filter((old) => !item.key || old.key !== item.key), item].slice(-3));
    };
    window.addEventListener(EVENT, receive);
    return () => window.removeEventListener(EVENT, receive);
  }, []);
  return <Toast.Provider duration={5000} swipeDirection="right">
    {items.map((item) => <Toast.Root key={item.id} onOpenChange={(open) => { if (!open) setItems((old) => old.filter((value) => value.id !== item.id)); }}
      className="flex items-start gap-3 rounded-xl border border-sage/30 bg-paper-raised p-4 text-sm text-ink shadow-lg">
      <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-sage" aria-hidden />
      <Toast.Title className="flex-1">{item.message}</Toast.Title>
      <Toast.Close aria-label="Đóng thông báo" className="rounded p-1 text-ink-muted focus-visible:outline-2 focus-visible:outline-ember"><X className="size-4" /></Toast.Close>
    </Toast.Root>)}
    <Toast.Viewport label="Thông báo thao tác" className="fixed right-4 bottom-4 z-[100] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 outline-none" />
  </Toast.Provider>;
}

/** Header theo File Manager donor: mục đích ngắn bên trái, hành động bên phải. */
export function PageHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
    <div><h1 className="text-3xl font-extrabold tracking-tight">{title}</h1><p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">{description}</p></div>
    {action && <div className="flex shrink-0 flex-wrap gap-2">{action}</div>}
  </div>;
}

export function HelpDetails({ title = "Cách dùng", children }: { title?: string; children: ReactNode }) {
  return <details className="rounded-lg border border-line px-3 py-2 text-sm text-ink-muted">
    <summary className="flex cursor-pointer items-center gap-2 font-medium text-ink focus-visible:outline-2 focus-visible:outline-ember"><CircleHelp className="size-4" aria-hidden />{title}</summary>
    <div className="mt-3 space-y-2 leading-relaxed">{children}</div>
  </details>;
}

export function ErrorFeedback({ message, retry, className }: { message: string; retry?: () => void; className?: string }) {
  return <Notice tone="rust" className={className}><p>{message}</p>{retry && <Button size="sm" variant="secondary" className="mt-2" onClick={retry}>Thử lại</Button>}</Notice>;
}

export function FieldError({ id, message }: { id: string; message: string | null }) {
  return message ? <p id={id} role="alert" className="mt-1 text-sm text-rust">{message}</p> : null;
}

/**
 * Nút chép một giá trị kỹ thuật (checksum, URI artifact) vào clipboard. Kết quả báo ngay trên nút và cho trình đọc màn
 * hình; Clipboard API có thể vắng mặt (trang không bảo mật) hoặc bị từ chối quyền nên lỗi phải hiện, không im lặng.
 */
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = () => {
    void Promise.resolve()
      .then(() => navigator.clipboard.writeText(value))
      .then(() => setState("copied"), () => setState("failed"));
  };
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`Chép ${label}`}
      title={state === "failed" ? "Không chép được; hãy chọn và chép tay" : `Chép ${label}`}
      className="inline-flex size-6 shrink-0 items-center justify-center rounded text-ink-muted hover:bg-paper-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-ember"
    >
      {state === "copied" ? <Check className="size-3.5 text-sage" aria-hidden /> : state === "failed" ? <X className="size-3.5 text-rust" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      <span className="sr-only" role="status">{state === "copied" ? "Đã chép" : state === "failed" ? "Không chép được" : ""}</span>
    </button>
  );
}
