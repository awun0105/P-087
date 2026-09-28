/**
 * Khung điều hướng của Web Studio.
 *
 * Mọi màn hình tối thiểu của PRODUCT-05 đi qua đây, nên đường dẫn trong
 * `NAV_SECTIONS` chính là danh sách route mà gate M1 kiểm tra.
 *
 * AppShell là Client Component để dùng `usePathname` cho active nav state.
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export interface NavItem {
  label: string;
  /** `null` khi đường dẫn cần `jobId` mà chưa biết job nào. */
  href: string | null;
  description: string;
  icon: string;
}

export const NAV_SECTIONS: NavItem[] = [
  {
    label: "Mở 3DGS",
    href: "/viewer",
    description: "Preview file Gaussian PLY/SOG cục bộ, không cần backend",
    icon: "◈",
  },
  {
    label: "Projects",
    href: "/projects",
    description: "Danh sách project và privacy state",
    icon: "⬡",
  },
  {
    label: "Job",
    href: null,
    description: "Trạng thái job, stage, attempt, retry",
    icon: "⚙",
  },
  {
    label: "Scene",
    href: null,
    description: "SceneIR viewer: 3DGS / mesh / point cloud / collider",
    icon: "◈",
  },
  {
    label: "Validation",
    href: null,
    description: "Báo cáo validation của candidate",
    icon: "✓",
  },
  {
    label: "Review",
    href: null,
    description: "Trạng thái review và authorization",
    icon: "◎",
  },
];

/** Đường dẫn của các màn hình gắn với một job cụ thể. */
export function jobRoutes(jobId: string): NavItem[] {
  return [
    {
      label: "Job",
      href: `/jobs/${jobId}`,
      description: "Trạng thái job, stage, attempt, retry",
      icon: "⚙",
    },
    {
      label: "Scene",
      href: `/jobs/${jobId}/viewer`,
      description: "SceneIR viewer",
      icon: "◈",
    },
    {
      label: "Validation",
      href: `/jobs/${jobId}/validation`,
      description: "Báo cáo validation",
      icon: "✓",
    },
    {
      label: "Review",
      href: `/jobs/${jobId}/review`,
      description: "Review và authorization",
      icon: "◎",
    },
    {
      label: "Release",
      href: `/jobs/${jobId}/release`,
      description: "Seal và phát hành candidate",
      icon: "⬆",
    },
  ];
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen flex-col bg-slate-950 text-slate-100">
      {/* Top bar */}
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-6 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-2 text-slate-50 transition-colors hover:text-white"
          >
            <span className="text-lg font-bold tracking-tight">Real2Sim</span>
            <span className="rounded border border-sky-900/40 bg-sky-950/60 px-1.5 py-0.5 font-mono text-xs text-sky-400">
              Studio
            </span>
          </Link>
          <span className="hidden text-xs text-slate-600 sm:block">EX-PRODUCT · mock-first</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-slate-500" title="Kết nối backend được kiểm tra tại màn hình gọi API" />
          <span className="hidden text-xs text-slate-500 sm:block">fixture mode</span>
        </div>
      </header>

      <div className="flex flex-1 flex-col md:flex-row">
        {/* Sidebar */}
        <nav className="w-full shrink-0 border-b border-slate-800 bg-slate-900/30 p-3 md:w-56 md:border-r md:border-b-0 md:py-5">
          <p className="mb-2 hidden px-2 text-[10px] font-semibold uppercase tracking-widest text-slate-600 md:block">
            Navigation
          </p>
          <ul className="flex flex-row flex-wrap gap-1 md:flex-col md:gap-0.5">
            {NAV_SECTIONS.map((item) => {
              const isActive = item.href
                ? pathname === item.href || pathname.startsWith(item.href + "/")
                : false;
              return (
                <li key={item.label}>
                  {item.href ? (
                    <Link
                      href={item.href}
                      title={item.description}
                      className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-all ${
                        isActive
                          ? "bg-sky-900/50 font-medium text-sky-300 ring-1 ring-sky-800/40"
                          : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                      }`}
                    >
                      <span className="w-4 shrink-0 text-center text-base leading-none">
                        {item.icon}
                      </span>
                      {item.label}
                    </Link>
                  ) : (
                    <span
                      title={`${item.description} — chọn một job trước`}
                      className="flex cursor-not-allowed select-none items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700"
                    >
                      <span className="w-4 shrink-0 text-center text-base leading-none">
                        {item.icon}
                      </span>
                      {item.label}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Main content */}
        <main className="min-w-0 flex-1 p-5 md:p-6">{children}</main>
      </div>
    </div>
  );
}

/** Thanh điều hướng giữa các màn hình của cùng một job. */
export function JobTabs({ jobId, active }: { jobId: string; active: string }) {
  return (
    <nav
      className="mb-5 flex flex-wrap gap-1.5 border-b border-slate-800 pb-3"
      data-testid="job-tabs"
    >
      {jobRoutes(jobId).map((item) => (
        <Link
          key={item.label}
          href={item.href!}
          aria-current={active === item.label ? "page" : undefined}
          className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
            active === item.label
              ? "bg-sky-700 text-white shadow-sm ring-1 ring-sky-600"
              : "bg-slate-800/80 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
          }`}
        >
          <span className="leading-none">{item.icon}</span>
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-5 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-50">{title}</h1>
        {subtitle && <p className="mt-0.5 font-mono text-sm text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

/** Card container tái dùng cho các section. */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-slate-800 bg-slate-900/50 p-4 ${className}`}>
      {children}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
      {children}
    </h2>
  );
}
