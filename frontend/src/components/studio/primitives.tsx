/**
 * Lớp component của app Studio (token beige/cam, từ vựng trạng thái sage/ochre/rust). Feature
 * import Button/Badge/Card/Notice… từ đây; `components/shadcn/*` là bộ nền (Radix) cho widget
 * phức tạp (sidebar, dialog, table, input). Button dựng trên Button của bộ nền để chỉ có một
 * hành vi gốc (focus, disabled, `asChild`), phần nhìn theo biến thể Studio bên dưới.
 */

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { Button as BaseButton } from "@/components/shadcn/button";
import { cn } from "@/lib/cn";

export const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-[10px] font-semibold whitespace-nowrap " +
    "transition-[background-color,border-color,color,transform] duration-200 outline-none select-none " +
    "focus-visible:ring-3 focus-visible:ring-ember/40 active:translate-y-px disabled:pointer-events-none " +
    "disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground shadow-sm hover:bg-ember",
        secondary: "border border-line-strong bg-paper-raised text-ink shadow-xs hover:border-ink-subtle hover:bg-paper-sunken",
        ghost: "text-ink-muted hover:bg-paper-sunken hover:text-ink",
        danger: "border border-rust/30 bg-rust-soft text-rust hover:bg-destructive-fill hover:text-white",
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

export type ButtonProps = ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean };

/** Biến thể Studio → biến thể bộ nền (giữ `data-variant` có nghĩa cho CSS/test). */
const BASE_VARIANT = { primary: "default", secondary: "outline", ghost: "ghost", danger: "destructive" } as const;

export function Button({ className, variant, size, asChild = false, type, ...props }: ButtonProps) {
  return (
    <BaseButton
      asChild={asChild}
      type={asChild ? undefined : (type ?? "button")}
      variant={BASE_VARIANT[variant ?? "primary"]}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

/**
 * Tên sản phẩm theo lockup của landing: "Real2Sim" đậm, "Studio" là nhãn mono trong khung nhỏ. Dùng ở sidebar và
 * trang đăng nhập để người đi từ landing sang app thấy cùng một tên.
 */
export function BrandWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-baseline gap-1.5", className)}>
      <span className="text-base font-bold tracking-tight text-ink">Real2Sim</span>{" "}
      <span className="rounded border border-line bg-paper-sunken px-1.5 py-0.5 font-mono text-[11px] leading-none font-semibold tracking-widest text-ink-muted uppercase">
        Studio
      </span>
    </span>
  );
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
        // scaleX thay vì width: đổi tiến độ không làm tính lại layout (mượt khi poll cập nhật).
        <div
          className="h-full w-full origin-left rounded-full bg-ember transition-transform duration-300 ease-out"
          style={{ transform: `scaleX(${clamped})` }}
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
      <h3 className="text-base font-bold text-ink">{title}</h3>
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
