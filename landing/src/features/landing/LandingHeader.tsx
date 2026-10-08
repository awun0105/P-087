"use client";

import { useEffect, useState } from "react";

import { NAV } from "@/features/landing/content";

export function LandingHeader({ tryDemoHref }: { tryDemoHref: string }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <header className="lp-header">
      <div className="lp-wrap flex min-h-16 items-center justify-between gap-4">
        <a href="#landing-top" className="flex items-center gap-2.5" aria-label="Real2Sim Studio, về đầu trang">
          <BrandMark />
          <span className="text-[17px] font-bold tracking-tight text-ink">Real2Sim</span>
          <span className="hidden rounded border border-line bg-paper-sunken min-[420px]:inline px-1.5 py-0.5 font-mono text-[11px] font-semibold text-ink-muted">
            Studio
          </span>
        </a>

        <nav aria-label="Các phần của trang" className="hidden items-center gap-7 text-[14px] font-medium text-ink-muted lg:flex">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className="py-1 transition-colors hover:text-ink">
              {n.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <a href={tryDemoHref} className="lp-btn lp-btn-primary lp-btn-sm">
            Thử scene mẫu
          </a>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="lp-mobile-nav"
            className="rounded-md border border-line p-2 text-ink-muted hover:bg-paper-sunken hover:text-ink lg:hidden"
          >
            <span className="sr-only">{open ? "Đóng menu" : "Mở menu"}</span>
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden>
              {open ? <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" /> : <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />}
            </svg>
          </button>
        </div>
      </div>

      {open ? (
        <nav id="lp-mobile-nav" aria-label="Các phần của trang" className="border-t border-line bg-paper-raised lg:hidden">
          <div className="lp-wrap flex flex-col py-3 text-[15px] font-medium text-ink">
            {NAV.map((n) => (
              <a key={n.href} href={n.href} onClick={() => setOpen(false)} className="py-2.5 hover:text-ember-strong">
                {n.label}
              </a>
            ))}
          </div>
        </nav>
      ) : null}
    </header>
  );
}

function BrandMark() {
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-md bg-viewport p-1.5" aria-hidden>
      <svg viewBox="0 0 24 24" fill="none" className="h-full w-full" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2L3 7l9 5 9-5-9-5z" stroke="var(--studio-ember)" strokeWidth="2" />
        <path d="M3 12l9 5 9-5" stroke="var(--studio-ochre)" strokeWidth="1.8" />
        <path d="M3 17l9 5 9-5" stroke="var(--studio-geometry)" strokeWidth="1.8" />
      </svg>
    </span>
  );
}
