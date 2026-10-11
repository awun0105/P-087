"use client";

import { ArrowLeft, Box, ChevronsUpDown, Clapperboard, LayoutDashboard, Loader2, LogIn, LogOut, PanelLeftClose, PanelLeftOpen, PlusCircle, Trash2, Users, UserRound } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ErrorFeedback } from "@/components/studio/feedback";
import { BrandWordmark } from "@/components/studio/primitives";
import { errorMessage } from "@/lib/ui-error";
import { useNavigationGuard } from "@/features/shell/NavigationGuard";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/shadcn/dropdown-menu";
import { Button } from "@/components/shadcn/button";
import { Separator } from "@/components/shadcn/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "@/components/shadcn/sidebar";
import { backHref, Breadcrumbs, PageTitleProvider } from "@/features/shell/Breadcrumbs";
import { PaletteMenu } from "@/features/shell/PaletteMenu";
import { ThemeToggle } from "@/features/shell/ThemeToggle";
import { useAuth } from "@/features/studio/AuthProvider";
import { GuestQuotaStatus } from "@/features/studio/auth/GuestQuotaStatus";
import { canEdit, isReviewer } from "@/lib/api/auth";
import { APP_HOME } from "@/lib/routes";

/** IA Tổng quan/Scenes theo STUDIO_UX_SPEC.md §3.1; mục tạo scene mới và quản lý scenes nằm trong Công việc. */
const NAV = [
  { heading: "Ứng dụng", items: [
    { href: APP_HOME, label: "Tổng quan", icon: LayoutDashboard, reviewerOnly: false },
  ] },
  { heading: "Công việc", items: [
    { href: "/new", label: "Tạo scene mới", icon: PlusCircle, reviewerOnly: false },
    { href: "/scenes", label: "Scenes", icon: Clapperboard, reviewerOnly: false },
    { href: "/trash", label: "Thùng rác", icon: Trash2, reviewerOnly: false },
  ] },
  { heading: "Quản lý", items: [
    { href: "/team", label: "Nhóm", icon: Users, reviewerOnly: true },
  ] },
] as const;

/** Trang không cần khung ứng dụng (đăng nhập/đăng ký có layout riêng). */
const BARE_ROUTES = ["/login", "/register"];

/** Route cho phép khách trải nghiệm mà không cần đăng nhập. */
export function isGuestAllowedRoute(pathname: string): boolean {
  if (pathname === "/new/try-demo" || pathname.startsWith("/new/try-demo")) return true;
  if (pathname.startsWith("/samples/")) return true;
  return false;
}

export function isActive(pathname: string, href: string): boolean {
  if (href === "/new") return pathname === "/new" || pathname.startsWith("/new/");
  if (href === "/scenes") return pathname === "/scenes" || ["/scenes/", "/imports/", "/samples/"].some((route) => pathname.startsWith(route));
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Khung ứng dụng theo shell của dashboard donor (sidebar thu gọn + header mảnh), bỏ search,
 * theme switcher, GitHub menu, account switcher mẫu (STUDIO_UX_SPEC.md §3.2). Tài khoản và hạn mức lấy
 * từ `/auth/me` — backend vẫn kiểm quyền trên từng route.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { me } = useAuth();
  const navigated = useRef(false);

  const isBare = BARE_ROUTES.some((route) => pathname.startsWith(route));
  const guestAllowed = isGuestAllowedRoute(pathname);
  const signedIn = canEdit(me);

  // Khi hệ thống yêu cầu đăng nhập và người dùng chưa có phiên:
  // Nếu vào trang workspace (không thuộc guestAllowed và không phải bare route), chuyển hướng về /login.
  const requiresAuthRedirect = !isBare && me !== null && me.auth_required && !me.user && !guestAllowed;

  useEffect(() => {
    if (requiresAuthRedirect && !navigated.current) {
      navigated.current = true;
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [requiresAuthRedirect, pathname, router]);

  if (isBare) return <>{children}</>;

  // Đang kiểm tra phiên trên route yêu cầu đăng nhập, hoặc đang chuyển hướng tới /login
  if ((me === null || requiresAuthRedirect) && !guestAllowed) {
    return (
      <div className="grid min-h-screen place-items-center bg-paper text-sm text-ink-muted" role="status">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="size-6 animate-spin text-primary motion-reduce:animate-none" aria-hidden />
          <p>Đang kiểm tra quyền truy cập…</p>
        </div>
      </div>
    );
  }

  return (
    <SidebarProvider>
      <PageTitleProvider key={pathname}>
        <AppSidebar pathname={pathname} signedIn={signedIn} />
        <SidebarInset className="min-w-0">
          <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background/80 px-3 backdrop-blur-md">
            {/* Màn hẹp: thanh bên là ngăn trượt nên header giữ nút mở; màn rộng thì nút thu gọn nằm trong thanh bên. */}
            <SidebarTrigger className="-ml-1 md:hidden" aria-label="Mở thanh bên" />
            <BackButton pathname={pathname} signedIn={signedIn} />
            <Breadcrumbs pathname={pathname} signedIn={signedIn} />
            <PaletteMenu className="ml-auto size-8 [&_svg]:size-4" />
            <ThemeToggle className="size-8 [&_svg]:size-4" />
          </header>
          <div className="min-h-0 min-w-0 flex-1">{children}</div>
        </SidebarInset>
      </PageTitleProvider>
    </SidebarProvider>
  );
}

/** Nút "Quay lại" ở đầu header; chỉ hiện trên trang con (có cấp cha trong breadcrumb). */
function BackButton({ pathname, signedIn }: { pathname: string; signedIn: boolean }) {
  const href = backHref(pathname, signedIn);
  if (!href) return null;
  return (
    <>
      <Button asChild variant="ghost" size="sm" className="-ml-1 gap-1.5 px-2">
        <Link href={href} aria-label="Quay lại trang trước">
          <ArrowLeft aria-hidden />
          <span className="hidden sm:inline">Quay lại</span>
        </Link>
      </Button>
      <Separator orientation="vertical" className="mx-1 data-[orientation=vertical]:h-4" />
    </>
  );
}

/**
 * Đầu thanh bên: logo + nút thu gọn. Khi thu gọn chỉ còn nút mở lại, đứng ở vị trí của logo và trên các mục điều hướng.
 */
function SidebarBrand({ signedIn }: { signedIn: boolean }) {
  const { state, isMobile, toggleSidebar } = useSidebar();
  const collapsed = state === "collapsed" && !isMobile;
  const label = collapsed ? "Mở thanh bên" : "Thu gọn thanh bên";
  return (
    <SidebarMenu>
      <SidebarMenuItem className="flex items-center gap-1">
        {!collapsed && (
          <SidebarMenuButton asChild size="lg" className="min-w-0 flex-1">
            <Link href={signedIn ? APP_HOME : "/"}>
              <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
                <Box className="size-4" aria-hidden />
              </span>
              <BrandWordmark />
            </Link>
          </SidebarMenuButton>
        )}
        <SidebarMenuButton
          tooltip={label}
          aria-label={label}
          aria-expanded={!collapsed}
          onClick={toggleSidebar}
          className={collapsed ? undefined : "size-8 w-8 flex-none justify-center"}
        >
          {collapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

function AppSidebar({ pathname, signedIn }: { pathname: string; signedIn: boolean }) {
  const { me } = useAuth();
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarBrand signedIn={signedIn} />
      </SidebarHeader>
      <SidebarContent>
        {signedIn ? (
          NAV.map((group) => {
            const items = group.items.filter((item) => !item.reviewerOnly || (me?.auth_required && isReviewer(me)));
            if (items.length === 0) return null;
            return (
              <SidebarGroup key={group.heading}>
                <SidebarGroupLabel>{group.heading}</SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {items.map((item) => (
                      <SidebarMenuItem key={item.href}>
                        <SidebarMenuButton asChild isActive={isActive(pathname, item.href)} tooltip={item.label}>
                          <Link href={item.href} aria-current={isActive(pathname, item.href) ? "page" : undefined}>
                            <item.icon aria-hidden />
                            <span>{item.label}</span>
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            );
          })
        ) : (
          <SidebarGroup>
            <SidebarGroupLabel>Chế độ xem mẫu</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton asChild isActive={pathname.startsWith("/new/try-demo") || pathname.startsWith("/samples/")} tooltip="Thử video mẫu">
                    <Link href="/new/try-demo">
                      <Clapperboard aria-hidden />
                      <span>Thử video mẫu</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
      <SidebarFooter>
        <AccountMenu pathname={pathname} />
      </SidebarFooter>
    </Sidebar>
  );
}

function AccountMenu({ pathname }: { pathname: string }) {
  const { me, logout } = useAuth();
  const { navigate } = useNavigationGuard();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function signOut() {
    setBusy(true); setError(null);
    try { await logout(); } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  if (me === null) {
    return null;
  }
  if (!me.auth_required) {
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
  const role = user.role === "reviewer" ? "Reviewer" : user.role === "editor" ? "Editor" : "Guest";
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
                {user.role === "guest"
                  ? " · tối đa 3 lượt chạy/ngày"
                  : user.role === "editor"
                    ? ` · hạn mức ${user.daily_job_quota} lần xử lý/ngày`
                    : " · không giới hạn lần xử lý"}
              </p>
              {user.role === "guest" && <GuestQuotaStatus quota={me.quota} className="mt-2" />}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild><Link href="/account"><UserRound aria-hidden />Tài khoản của tôi</Link></DropdownMenuItem>
            <DropdownMenuItem disabled={busy} onSelect={() => void navigate(() => { void signOut(); }, undefined, true)}>
              <LogOut aria-hidden />
              Đăng xuất
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {error && <ErrorFeedback message={error} />}
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
