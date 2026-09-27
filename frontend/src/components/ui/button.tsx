import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  busy?: boolean;
  icon?: ReactNode;
}

const variantMap: Record<ButtonVariant, string> = {
  primary:
    "bg-sky-600 text-white hover:bg-sky-500 focus:ring-sky-400/40 shadow-sm",
  secondary:
    "bg-slate-700 text-slate-100 hover:bg-slate-600 focus:ring-slate-400/40",
  ghost:
    "bg-slate-800/60 text-slate-300 hover:bg-slate-700 hover:text-slate-100 focus:ring-slate-400/30",
  danger:
    "bg-rose-600 text-white hover:bg-rose-500 focus:ring-rose-400/40 shadow-sm",
  subtle:
    "bg-transparent text-slate-400 hover:bg-slate-800 hover:text-slate-200 focus:ring-slate-400/30",
};

const sizeMap: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1.5 text-xs gap-1.5",
  md: "px-4 py-2 text-sm gap-2",
};

export function Button({
  variant = "primary",
  size = "md",
  busy = false,
  icon,
  children,
  disabled,
  className = "",
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || busy}
      className={`
        inline-flex items-center justify-center rounded-lg font-medium transition-all
        focus:outline-none focus:ring-2 focus:ring-offset-0 focus:ring-offset-slate-950
        disabled:cursor-not-allowed disabled:opacity-50
        ${variantMap[variant]} ${sizeMap[size]} ${className}
      `}
      {...rest}
    >
      {busy ? (
        <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}
