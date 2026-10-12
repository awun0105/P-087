"use client";

import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { SOURCE_ROUTES, SOURCE_TITLES } from "@/features/studio/newSceneSources";
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

/** Tên ba trang bắt đầu dưới `/new` lấy từ cùng nguồn với tiêu đề trang (features/studio/newSceneSources.ts). */
const NEW_SCENE_PAGES: Record<string, string> = {
  [SOURCE_ROUTES.video]: SOURCE_TITLES.video.title,
  [SOURCE_ROUTES.gaussian]: SOURCE_TITLES.gaussian.title,
  [SOURCE_ROUTES.sample]: SOURCE_TITLES.sample.title,
};

export function crumbsFor(pathname: string, detailTitle?: string | null, signedIn = true): Crumb[] {
  if (!signedIn) {
    if (pathname === "/new/try-demo" || pathname.startsWith("/new/try-demo")) {
      return [{ label: "Thử video mẫu" }];
    }
    if (pathname.startsWith("/samples/")) {
      return [
        { label: "Thử video mẫu", href: "/new/try-demo" },
        { label: detailTitle ?? "Video mẫu" },
      ];
    }
  }

  const scenes: Crumb = { label: "Scenes từ video", href: "/scenes" };
  const imports: Crumb = { label: "Scenes đã import", href: "/imports" };
  if (pathname === APP_HOME) return [{ label: "Tổng quan" }];
  if (pathname === "/scenes") return [{ label: "Scenes từ video" }];
  if (pathname === "/imports") return [{ label: "Scenes đã import" }];
  const start = NEW_SCENE_PAGES[pathname];
  if (start) return [{ label: "Tạo scene mới", href: "/new" }, { label: start }];
  if (pathname === "/new" || pathname.startsWith("/new")) return [{ label: "Tạo scene mới" }];
  if (pathname.startsWith("/jobs")) return [{ label: "Jobs" }];
  if (pathname.startsWith("/trash")) return [{ label: "Thùng rác" }];
  if (pathname.startsWith("/team")) return [{ label: "Nhóm" }];
  if (pathname === "/account") return [{ label: "Tài khoản" }];
  if (pathname.startsWith("/imports/")) return [imports, { label: detailTitle ?? "Đang tải scene…" }];
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
export function backHref(pathname: string, signedIn = true): string | null {
  if (!signedIn) {
    if (pathname === "/new/try-demo" || pathname.startsWith("/new/try-demo")) {
      return "/login";
    }
    if (pathname.startsWith("/samples/")) {
      return "/new/try-demo";
    }
  }
  // Trang tài khoản mở từ menu người dùng, không có mục điều hướng riêng nên quay về trang chủ của app.
  if (pathname === "/account") return APP_HOME;
  const parents = crumbsFor(pathname, null, signedIn).slice(0, -1).filter((crumb) => crumb.href);
  return parents.at(-1)?.href ?? null;
}

export function Breadcrumbs({ pathname, signedIn = true }: { pathname: string; signedIn?: boolean }) {
  const context = useContext(PageTitleContext);
  const crumbs = crumbsFor(pathname, context?.title, signedIn);
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
