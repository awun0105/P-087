import { Check } from "lucide-react";

import { cn } from "@/lib/cn";

export interface FlowStep {
  key: string;
  label: string;
}

/** Chỉ báo bước ngang ("Bước 2/4") — người dùng luôn biết mình đang ở đâu trong luồng. */
export function FlowStepper({ steps, current }: { steps: readonly FlowStep[]; current: number }) {
  return (
    <nav aria-label="Các bước" className="w-full">
      <p className="mb-3 text-xs font-medium tracking-wide text-ink-subtle uppercase sm:hidden">
        Bước {current + 1}/{steps.length} · {steps[current]?.label}
      </p>
      <ol className="hidden items-center gap-2 sm:flex">
        {steps.map((step, index) => {
          const done = index < current;
          const active = index === current;
          return (
            <li key={step.key} className="flex flex-1 items-center gap-2 last:flex-none">
              <span
                aria-current={active ? "step" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-full py-1 pr-3 pl-1 text-sm transition-colors duration-200",
                  active ? "bg-ember-soft font-medium text-ink" : done ? "text-ink-muted" : "text-ink-subtle",
                )}
              >
                <span
                  className={cn(
                    "grid size-6 place-items-center rounded-full text-xs font-semibold",
                    done && "bg-sage text-paper",
                    active && "bg-ember-strong text-white",
                    !done && !active && "border border-line-strong text-ink-subtle",
                  )}
                >
                  {done ? <Check className="size-3.5" aria-hidden /> : index + 1}
                </span>
                {step.label}
                {done && <span className="sr-only">(đã xong)</span>}
              </span>
              {index < steps.length - 1 && (
                <span className={cn("h-px flex-1", done ? "bg-ink/40" : "bg-line-strong")} aria-hidden />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
