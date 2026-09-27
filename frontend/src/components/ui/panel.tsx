import type { ReactNode } from "react";

interface PanelProps {
  children: ReactNode;
  className?: string;
}

export function Panel({ children, className = "" }: PanelProps) {
  return (
    <div
      className={`
        overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50
        ${className}
      `}
    >
      {children}
    </div>
  );
}

interface PanelHeaderProps {
  title: string;
  actions?: ReactNode;
  subtitle?: string;
}

export function PanelHeader({ title, actions, subtitle }: PanelHeaderProps) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</h3>
        {subtitle && <p className="mt-0.5 text-[10px] text-slate-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
