/**
 * UI primitive của Studio MVP, adapt từ pattern shadcn/ui (button/card/badge/
 * progress) trong `next-shadcn-admin-dashboard` (MIT) sang token beige/cam.
 * Không dùng Radix: các thành phần ở đây đủ bằng HTML gốc + aria.
 */

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

export const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-[10px] font-medium whitespace-nowrap " +
    "transition-[background-color,border-color,color,transform] duration-200 outline-none select-none " +
    "focus-visible:ring-3 focus-visible:ring-ember/40 active:translate-y-px disabled:pointer-events-none " +
    "disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-ember-strong text-white shadow-sm hover:bg-ember",
        secondary: "border border-line-strong bg-paper-raised text-ink hover:border-ink-subtle hover:bg-paper",
        ghost: "text-ink-muted hover:bg-paper-sunken hover:text-ink",
        danger: "border border-rust/30 bg-rust-soft text-rust hover:bg-rust hover:text-white",
      },
      size: {
        sm: "h-8 px-3 text-sm [&_svg]:size-4",
        md: "h-10 px-4 text-sm [&_svg]:size-4",
        lg: "h-12 px-6 text-base [&_svg]:size-5",
        icon: "size-10 [&_svg]:size-5",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = ComponentProps<"button"> & VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn("rounded-2xl border border-line bg-paper-raised shadow-[0_1px_2px_rgb(43_37_32/0.04)]", className)}
      {...props}
    />
  );
}

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap [&_svg]:size-3.5",
  {
    variants: {
      tone: {
        neutral: "bg-paper-sunken text-ink-muted",
        ember: "bg-ember-soft text-ember-strong",
        sage: "bg-sage-soft text-sage",
        ochre: "bg-ochre-soft text-ochre",
        rust: "bg-rust-soft text-rust",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/**
 * Thanh tiến trình. `value` null = đang chạy nhưng không đo được phần trăm
 * (PRODUCT-09: không bịa số) → hiển thị dải chạy thay vì con số.
 */
export function ProgressBar({
  value,
  label,
  className,
}: {
  value: number | null;
  label: string;
  className?: string;
}) {
  const clamped = value === null ? null : Math.min(1, Math.max(0, value));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped === null ? undefined : Math.round(clamped * 100)}
      className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-paper-sunken", className)}
    >
      {clamped === null ? (
        <div className="studio-indeterminate absolute inset-y-0 w-1/3 rounded-full bg-ember" />
      ) : (
        <div
          className="h-full rounded-full bg-ember transition-[width] duration-300 ease-out"
          style={{ width: `${clamped * 100}%` }}
        />
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center rounded-2xl border border-dashed border-line-strong px-6 py-14 text-center",
        className,
      )}
    >
      <div className="mb-4 grid size-12 place-items-center rounded-full bg-ember-soft text-ember-strong [&_svg]:size-6">
        {icon}
      </div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {children && <div className="mt-1.5 max-w-md text-sm text-ink-muted">{children}</div>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function Notice({
  tone = "neutral",
  icon,
  children,
  className,
}: {
  tone?: "neutral" | "ember" | "rust" | "ochre";
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const tones = {
    neutral: "border-line bg-paper-raised text-ink-muted",
    ember: "border-ember/30 bg-ember-soft text-ink",
    rust: "border-rust/30 bg-rust-soft text-rust",
    ochre: "border-ochre/30 bg-ochre-soft text-ink",
  } as const;
  return (
    <div
      role={tone === "rust" ? "alert" : "note"}
      className={cn("flex gap-3 rounded-xl border px-4 py-3 text-sm [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0", tones[tone], className)}
    >
      {icon}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Định dạng dung lượng file theo đơn vị nhị phân, 1 chữ số thập phân. */
export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** "3 phút 12 giây" — thời lượng đo được, không làm tròn thành ước lượng. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  if (hours > 0) return `${hours} giờ ${minutes} phút`;
  if (minutes > 0) return `${minutes} phút ${rest} giây`;
  return `${rest} giây`;
}
