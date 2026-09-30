"use client";

import { Box, LogIn, LogOut, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Badge, Button, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { isReviewer } from "@/lib/api/auth";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", label: "Scenes", reviewerOnly: false },
  { href: "/team", label: "Nhóm", reviewerOnly: true },
] as const;

/** Thanh trên cùng tối giản: logo, điều hướng, một nút hành động chính. */
export function StudioHeader() {
  const pathname = usePathname();
  const { me, logout } = useAuth();
  const nav = NAV.filter((item) => !item.reviewerOnly || (me?.auth_required && isReviewer(me)));
  return (
    <header className="sticky top-0 z-30 border-b border-line/80 bg-paper/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 rounded-lg text-ink focus-visible:ring-3 focus-visible:ring-ember/40 focus-visible:outline-none">
          <span className="grid size-8 place-items-center rounded-lg bg-ink text-ink">
            <Box className="size-4" aria-hidden />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">Real2Sim Studio</span>
        </Link>
        <nav aria-label="Điều hướng chính" className="hidden items-center gap-1 sm:flex">
          {nav.map((item) => {
            const active = item.href === "/" ? pathname === "/" || pathname.startsWith("/scenes") : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-lg px-3 py-2 text-sm transition-colors duration-200",
                  active ? "bg-paper-sunken font-medium text-ink" : "text-ink-muted hover:text-ink",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/new" className={buttonVariants({ variant: "secondary", size: "sm" })}>
            <Plus aria-hidden />
            Scene mới
          </Link>
          {me?.auth_required &&
            (me.user ? (
              <div className="flex items-center gap-2 border-l border-line pl-2">
                <span className="hidden text-sm text-ink-muted md:inline">{me.user.display_name}</span>
                <Badge tone={me.user.role === "reviewer" ? "ember" : "neutral"}>
                  {me.user.role === "reviewer" ? "Reviewer" : "Editor"}
                </Badge>
                <Button variant="ghost" size="sm" onClick={() => void logout()} aria-label="Đăng xuất">
                  <LogOut aria-hidden />
                </Button>
              </div>
            ) : (
              <Link
                href={`/login?next=${encodeURIComponent(pathname)}`}
                className={buttonVariants({ variant: "ghost", size: "sm" })}
              >
                <LogIn aria-hidden />
                Đăng nhập
              </Link>
            ))}
        </div>
      </div>
    </header>
  );
}
