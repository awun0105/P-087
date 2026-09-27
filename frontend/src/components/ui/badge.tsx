import type { ReactNode } from "react";

type BadgeTone = "default" | "ok" | "warn" | "danger" | "info" | "muted";

interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}

const toneMap: Record<BadgeTone, string> = {
  default: "bg-slate-700 text-slate-100",
  ok: "bg-emerald-900/70 text-emerald-300 border-emerald-900",
  warn: "bg-amber-900/70 text-amber-300 border-amber-900",
  danger: "bg-rose-900/70 text-rose-300 border-rose-900",
  info: "bg-sky-900/70 text-sky-300 border-sky-900",
  muted: "bg-slate-800 text-slate-500 border-slate-800",
};

export function Badge({ tone = "default", children, className = "" }: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide
        ${toneMap[tone]} ${className}
      `}
    >
      {children}
    </span>
  );
}
