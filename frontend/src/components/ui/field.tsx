import type { ReactNode } from "react";

interface FieldProps {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}

export function Field({ label, hint, error, children }: FieldProps) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium text-slate-500">{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-[10px] text-slate-600">{hint}</p>}
      {error && <p className="mt-1 text-[10px] text-rose-400">{error}</p>}
    </div>
  );
}
