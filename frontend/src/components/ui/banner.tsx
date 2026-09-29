import type { ReactNode } from "react";

type BannerTone = "info" | "warn" | "danger" | "mock";

interface BannerProps {
  tone?: BannerTone;
  title?: string;
  children: ReactNode;
  testId?: string;
}

const toneMap: Record<BannerTone, string> = {
  info: "border-sky-900/60 bg-sky-950/30 text-sky-200",
  warn: "border-amber-800/60 bg-amber-950/40 text-amber-200",
  danger: "border-rose-900/60 bg-rose-950/40 text-rose-200",
  mock: "border-slate-700 bg-slate-900/70 text-slate-400",
};

export function Banner({ tone = "info", title, children, testId }: BannerProps) {
  return (
    <div
      data-testid={testId}
      className={`
        rounded-xl border p-3 text-xs leading-relaxed
        ${toneMap[tone]}
      `}
    >
      {title && <p className="mb-1 font-semibold">{title}</p>}
      {children}
    </div>
  );
}
