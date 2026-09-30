"use client";

import Link from "next/link";
import { Fragment } from "react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/shadcn/breadcrumb";

interface Crumb {
  label: string;
  href?: string;
}

/** Breadcrumb suy từ đường dẫn; tên scene cụ thể do màn scene tự hiển thị trong nội dung (P4). */
export function crumbsFor(pathname: string): Crumb[] {
  const scenes: Crumb = { label: "Scenes", href: "/" };
  if (pathname === "/") return [{ label: "Scenes" }];
  if (pathname.startsWith("/new")) return [scenes, { label: "Scene mới" }];
  if (pathname.startsWith("/jobs")) return [{ label: "Jobs" }];
  if (pathname.startsWith("/team")) return [{ label: "Nhóm" }];
  if (pathname.startsWith("/imports/")) return [scenes, { label: "Scene import" }];
  if (pathname.startsWith("/samples/")) return [scenes, { label: "Video mẫu" }];
  if (pathname.startsWith("/scenes/")) return [scenes, { label: "Scene" }];
  return [scenes];
}

export function Breadcrumbs({ pathname }: { pathname: string }) {
  const crumbs = crumbsFor(pathname);
  return (
    <Breadcrumb>
      <BreadcrumbList>
        {crumbs.map((crumb, index) => (
          <Fragment key={`${crumb.label}-${index}`}>
            {index > 0 && <BreadcrumbSeparator />}
            <BreadcrumbItem>
              {crumb.href ? (
                <BreadcrumbLink asChild>
                  <Link href={crumb.href}>{crumb.label}</Link>
                </BreadcrumbLink>
              ) : (
                <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
              )}
            </BreadcrumbItem>
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
