/**
 * Khung điều hướng của Web Studio.
 *
 * Mọi màn hình tối thiểu của PRODUCT-05 đi qua đây, nên đường dẫn trong
 * `NAV_SECTIONS` chính là danh sách route mà gate M1 kiểm tra.
 */

import Link from "next/link";
import type { ReactNode } from "react";

export interface NavItem {
  label: string;
  /** `null` khi đường dẫn cần `jobId` mà chưa biết job nào. */
  href: string | null;
  description: string;
}

export const NAV_SECTIONS: NavItem[] = [
  { label: "Projects", href: "/projects", description: "Danh sách project và privacy state" },
  { label: "Job", href: null, description: "Trạng thái job, stage, attempt, retry" },
  { label: "Scene", href: null, description: "SceneIR viewer: 3DGS / mesh / point cloud / collider" },
  { label: "Validation", href: null, description: "Báo cáo validation của candidate" },
  { label: "Review", href: null, description: "Trạng thái review và authorization" },
];

/** Đường dẫn của các màn hình gắn với một job cụ thể. */
export function jobRoutes(jobId: string): NavItem[] {
  return [
    { label: "Job", href: `/jobs/${jobId}`, description: "Trạng thái job, stage, attempt, retry" },
    { label: "Scene", href: `/jobs/${jobId}/viewer`, description: "SceneIR viewer" },
    { label: "Validation", href: `/jobs/${jobId}/validation`, description: "Báo cáo validation" },
    { label: "Review", href: `/jobs/${jobId}/review`, description: "Review và authorization" },
  ];
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-3">
        <div className="flex items-baseline gap-3">
          <Link href="/" className="text-lg font-semibold text-slate-50">
            Real2Sim Studio
          </Link>
          <span className="text-xs text-slate-400">EX-PRODUCT · mock-first</span>
        </div>
      </header>
      <div className="flex flex-1 flex-col md:flex-row">
        <nav className="w-full shrink-0 border-b border-slate-800 p-4 md:w-56 md:border-r md:border-b-0">
          <ul className="flex flex-row gap-3 md:flex-col md:gap-1">
            {NAV_SECTIONS.map((item) => (
              <li key={item.label}>
                {item.href ? (
                  <Link
                    href={item.href}
                    className="block rounded px-2 py-1 text-sm text-slate-300 hover:bg-slate-800"
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span className="block px-2 py-1 text-sm text-slate-600" title="chọn một job trước">
                    {item.label}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </nav>
        <main className="min-w-0 flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

/** Thanh điều hướng giữa các màn hình của cùng một job. */
export function JobTabs({ jobId, active }: { jobId: string; active: string }) {
  return (
    <nav className="mb-4 flex flex-wrap gap-2" data-testid="job-tabs">
      {jobRoutes(jobId).map((item) => (
        <Link
          key={item.label}
          href={item.href!}
          aria-current={active === item.label ? "page" : undefined}
          className={`rounded px-3 py-1 text-sm ${
            active === item.label ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
          }`}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="mb-4">
      <h1 className="text-xl font-semibold text-slate-50">{title}</h1>
      {subtitle && <p className="text-sm text-slate-400">{subtitle}</p>}
    </header>
  );
}
