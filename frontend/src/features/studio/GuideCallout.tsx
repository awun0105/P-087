import { MousePointerClick } from "lucide-react";
import type { ReactNode } from "react";

/** Khung hướng dẫn của kịch bản demo: nói rõ bước hiện tại và việc cần bấm tiếp. */
export function GuideCallout({ step, total, title, children }: { step: number; total: number; title: string; children: ReactNode }) {
  return (
    <aside
      aria-label="Hướng dẫn"
      className="flex gap-4 rounded-2xl border border-ember/25 bg-gradient-to-br from-ember-soft to-paper-raised p-5"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-full bg-ember-strong text-white">
        <MousePointerClick className="size-4" aria-hidden />
      </span>
      <div className="min-w-0">
        <p className="text-xs font-semibold tracking-wide text-ember-strong uppercase">
          Hướng dẫn · Bước {step}/{total}
        </p>
        <p className="mt-1 text-base font-semibold text-ink">{title}</p>
        <div className="mt-1 text-sm leading-relaxed text-ink-muted">{children}</div>
      </div>
    </aside>
  );
}
