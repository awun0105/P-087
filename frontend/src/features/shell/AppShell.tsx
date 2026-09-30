"use client";

import { Box, ChevronsUpDown, Clapperboard, ListChecks, LogIn, LogOut, Plus, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/shadcn/dropdown-menu";
import { Separator } from "@/components/shadcn/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/shadcn/sidebar";
import { Breadcrumbs } from "@/features/shell/Breadcrumbs";
import { useAuth } from "@/features/studio/AuthProvider";
import { isReviewer } from "@/lib/api/auth";

/** Điều hướng toàn cục chỉ gồm Scenes · Jobs · Nhóm (PRODUCT.md §3.1); phần khác nằm trong ngữ cảnh scene. */
const NAV = [
  { href: "/", label: "Scenes", icon: Clapperboard, reviewerOnly: false },
  { href: "/jobs", label: "Jobs", icon: ListChecks, reviewerOnly: false },
  { href: "/team", label: "Nhóm", icon: Users, reviewerOnly: true },
] as const;

/** Trang không cần khung ứng dụng (đăng nhập/đăng ký có layout riêng). */
const BARE_ROUTES = ["/login", "/register"];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/" || pathname.startsWith("/scenes") || pathname.startsWith("/imports");
  return pathname.startsWith(href);
}

/**
 * Khung ứng dụng theo shell của dashboard donor (sidebar thu gọn + header mảnh), bỏ search,
 * theme switcher, GitHub menu, account switcher mẫu (PRODUCT.md §3.2). Tài khoản và hạn mức lấy
 * từ `/auth/me` — backend vẫn kiểm quyền trên từng route.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (BARE_ROUTES.some((route) => pathname.startsWith(route))) return <>{children}</>;
  return (
    <SidebarProvider>
      <AppSidebar pathname={pathname} />
      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background/80 px-3 backdrop-blur-md">
          <SidebarTrigger className="-ml-1" aria-label="Thu gọn / mở thanh bên" />
          <Separator orientation="vertical" className="mx-1 data-[orientation=vertical]:h-4" />
          <Breadcrumbs pathname={pathname} />
        </header>
        <div className="min-h-0 min-w-0 flex-1">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}

function AppSidebar({ pathname }: { pathname: string }) {
  const { me } = useAuth();
  const nav = NAV.filter((item) => !item.reviewerOnly || (me?.auth_required && isReviewer(me)));
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild size="lg" tooltip="Real2Sim Studio">
              <Link href="/">
                <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
                  <Box className="size-4" aria-hidden />
                </span>
                <span className="font-semibold tracking-tight">Real2Sim Studio</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="Scene mới" className="bg-primary text-primary-foreground hover:bg-primary/85 hover:text-primary-foreground">
              <Link href="/new">
                <Plus aria-hidden />
                <span>Scene mới</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {nav.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton asChild isActive={isActive(pathname, item.href)} tooltip={item.label}>
                    <Link href={item.href}>
                      <item.icon aria-hidden />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <AccountMenu pathname={pathname} />
      </SidebarFooter>
    </Sidebar>
  );
}

function AccountMenu({ pathname }: { pathname: string }) {
  const { me, logout } = useAuth();
  if (!me?.auth_required) {
    // Deployment local không bật đăng nhập: không có tài khoản để hiện, không giả một user.
    return <p className="px-2 text-xs text-sidebar-foreground/60 group-data-[collapsible=icon]:hidden">Chế độ local · không đăng nhập</p>;
  }
  if (!me.user) {
    return (
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton asChild tooltip="Đăng nhập">
            <Link href={`/login?next=${encodeURIComponent(pathname)}`}>
              <LogIn aria-hidden />
              <span>Đăng nhập</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    );
  }
  const user = me.user;
  const role = user.role === "reviewer" ? "Reviewer" : "Editor";
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg" tooltip={user.display_name}>
              <span className="grid size-8 place-items-center rounded-lg bg-sidebar-accent text-sm font-semibold uppercase">
                {user.display_name.slice(0, 1)}
              </span>
              <span className="grid min-w-0 flex-1 text-left leading-tight">
                <span className="truncate text-sm font-medium">{user.display_name}</span>
                <span className="truncate text-xs text-sidebar-foreground/60">{role}</span>
              </span>
              <ChevronsUpDown className="ml-auto size-4" aria-hidden />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="end" className="min-w-56">
            <DropdownMenuLabel className="font-normal">
              <p className="text-sm font-medium">{user.display_name}</p>
              <p className="text-xs text-muted-foreground">{user.email}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {role}
                {user.role === "editor" ? ` · hạn mức ${user.daily_job_quota} lần xử lý/ngày` : " · không giới hạn lần xử lý"}
              </p>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void logout()}>
              <LogOut aria-hidden />
              Đăng xuất
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
