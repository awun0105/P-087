"use client";

import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { createContext, Fragment, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/shadcn/breadcrumb";
import { inspectionStage, progressHref } from "@/features/studio/inspection";
import { APP_HOME } from "@/lib/routes";

interface Crumb {
  label: string;
  href?: string;
}

const PageTitleContext = createContext<{ title: string | null; setTitle: (title: string | null) => void } | null>(null);

/** Màn chi tiết đăng ký tên lấy từ API; shell không tự suy tên từ URL hoặc giữ business state. */
export function PageTitleProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState<string | null>(null);
  const value = useMemo(() => ({ title, setTitle }), [title]);
  return <PageTitleContext.Provider value={value}>{children}</PageTitleContext.Provider>;
}

export function usePageTitle(title: string | null): void {
  const context = useContext(PageTitleContext);
  if (!context) throw new Error("usePageTitle cần nằm trong PageTitleProvider");
  const { setTitle } = context;
  useEffect(() => {
    setTitle(title);
    return () => setTitle(null);
  }, [setTitle, title]);
}

export function crumbsFor(pathname: string, detailTitle?: string | null): Crumb[] {
  const scenes: Crumb = { label: "Scenes", href: "/scenes" };
  if (pathname === APP_HOME) return [{ label: "Tổng quan" }];
  if (pathname === "/scenes") return [{ label: "Scenes" }];
  if (pathname.startsWith("/new")) return [scenes, { label: "Scene mới" }];
  if (pathname.startsWith("/jobs")) return [{ label: "Jobs" }];
  if (pathname.startsWith("/team")) return [{ label: "Nhóm" }];
  if (pathname === "/account") return [{ label: "Tài khoản" }];
  if (pathname.startsWith("/imports/")) return [scenes, { label: detailTitle ?? "Scene import" }];
  if (pathname.startsWith("/samples/")) return [scenes, { label: detailTitle ?? "Video mẫu" }];
  const inspection = /^\/scenes\/([^/]+)\/stages\/([^/]+)$/.exec(pathname);
  if (inspection) return [scenes, { label: detailTitle ?? "Scene", href: progressHref(decodeURIComponent(inspection[1])) }, { label: inspectionStage(inspection[2])?.title ?? "Giai đoạn" }];
  if (pathname.startsWith("/scenes/")) return [scenes, { label: detailTitle ?? "Đang tải scene…" }];
  return [{ label: "Tổng quan", href: APP_HOME }];
}

/**
 * Đích của nút "Quay lại" trên header: cấp cha gần nhất trong breadcrumb. Dùng đường dẫn xác định thay cho lịch sử trình
 * duyệt để mở trang con bằng link trực tiếp vẫn quay về đúng chỗ; trang cấp cao nhất trả null (không có nút).
 */
export function backHref(pathname: string): string | null {
  // Trang tài khoản mở từ menu người dùng, không có mục điều hướng riêng nên quay về trang chủ của app.
  if (pathname === "/account") return APP_HOME;
  const parents = crumbsFor(pathname).slice(0, -1).filter((crumb) => crumb.href);
  return parents.at(-1)?.href ?? null;
}

export function Breadcrumbs({ pathname }: { pathname: string }) {
  const context = useContext(PageTitleContext);
  const crumbs = crumbsFor(pathname, context?.title);
  return (
    <Breadcrumb className="min-w-0">
      <BreadcrumbList className="flex-nowrap">
        {crumbs.map((crumb, index) => (
          <Fragment key={`${crumb.label}-${index}`}>
            {index > 0 && <BreadcrumbSeparator />}
            <BreadcrumbItem className="min-w-0">
              {crumb.href ? (
                <BreadcrumbLink asChild>
                  <Link href={crumb.href}>{crumb.label}</Link>
                </BreadcrumbLink>
              ) : (
                <BreadcrumbPage className="truncate" title={crumb.label}>{crumb.label}</BreadcrumbPage>
              )}
            </BreadcrumbItem>
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
