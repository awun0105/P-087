"use client";

import { Box, Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { buttonVariants } from "@/components/studio/primitives";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", label: "Scenes" },
  { href: "/demo", label: "Kịch bản demo" },
] as const;

/** Thanh trên cùng tối giản: logo, 2 mục điều hướng, một nút hành động chính. */
export function StudioHeader() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b border-line/80 bg-paper/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 rounded-lg text-ink focus-visible:ring-3 focus-visible:ring-ember/40 focus-visible:outline-none">
          <span className="grid size-8 place-items-center rounded-lg bg-ink text-paper">
            <Box className="size-4" aria-hidden />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">Real2Sim Studio</span>
        </Link>
        <nav aria-label="Điều hướng chính" className="hidden items-center gap-1 sm:flex">
          {NAV.map((item) => {
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
                {item.href === "/demo" && <Sparkles className="mr-1.5 inline size-3.5 text-ember-strong" aria-hidden />}
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/demo" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "sm:hidden")}>
            Demo
          </Link>
          <Link href="/new" className={buttonVariants({ variant: "secondary", size: "sm" })}>
            <Plus aria-hidden />
            Scene mới
          </Link>
        </div>
      </div>
    </header>
  );
}
