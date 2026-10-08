"use client";

import { Globe } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";

import { getContent, getUiLabels } from "@/features/landing/content";
import { PaletteMenu } from "@/features/shell/PaletteMenu";
import { ThemeToggle } from "@/features/shell/ThemeToggle";
import { STUDIO_LOGIN_URL } from "@/lib/api";
import { applyLanguage, currentLanguage, subscribeLanguage, type Language } from "@/lib/i18n";

const serverLang = (): Language => "vi";

export function LandingHeader({
  tryDemoHref,
  studioHref = STUDIO_LOGIN_URL,
}: {
  tryDemoHref: string;
  studioHref?: string;
}) {
  const [open, setOpen] = useState(false);
  const lang = useSyncExternalStore(subscribeLanguage, currentLanguage, serverLang);

  const content = getContent(lang);
  const ui = getUiLabels(lang);

  const nextLang: Language = lang === "vi" ? "en" : "vi";
  const langLabel = lang === "vi" ? ui.langToEn : ui.langToVi;

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
      <div className="lp-wrap flex min-h-16 items-center justify-between gap-2 lg:gap-3 xl:gap-6">
        <a href="#landing-top" className="flex shrink-0 items-center gap-2" aria-label={ui.brandAria}>
          <BrandMark />
          <span className="whitespace-nowrap text-[17px] font-bold tracking-tight text-ink">Real2Sim</span>
          <span className="hidden whitespace-nowrap rounded border border-line bg-paper-sunken px-1.5 py-0.5 font-mono text-[11px] font-semibold text-ink-muted xl:inline">
            Studio
          </span>
        </a>

        <nav
          aria-label={ui.navAria}
          className="hidden shrink-0 items-center gap-2 text-[13px] font-medium text-ink-muted whitespace-nowrap lg:flex lg:gap-2.5 xl:gap-4 2xl:gap-5.5 xl:text-[14px]"
        >
          {content.NAV.map((n) => (
            <a key={n.href} href={n.href} className="whitespace-nowrap rounded px-1.5 py-1 transition-colors hover:text-ink">
              {n.label}
            </a>
          ))}
        </nav>

        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          {/* Thử scene mẫu */}
          <a
            href={tryDemoHref}
            className="lp-btn lp-btn-primary lp-btn-sm h-8 min-h-[32px] whitespace-nowrap px-2.5 text-xs font-semibold sm:px-3 sm:text-[13px]"
          >
            {ui.tryDemo}
          </a>

          {/* Truy cập Studio */}
          <a
            href={studioHref}
            className="lp-btn lp-btn-ghost lp-btn-sm hidden h-8 min-h-[32px] whitespace-nowrap px-2.5 text-xs font-semibold sm:inline-flex sm:px-3 sm:text-[13px]"
          >
            {ui.openStudio}
          </a>

          {/* Phân cách giữa CTA và nhóm tiện ích */}
          <div className="hidden h-4 w-px bg-line sm:block mx-0.5" aria-hidden />

          {/* Đổi ngôn ngữ */}
          <button
            type="button"
            onClick={() => applyLanguage(nextLang)}
            aria-label={langLabel}
            title={langLabel}
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-line px-2 font-mono text-xs font-semibold text-ink-muted transition-colors hover:bg-paper-sunken hover:text-ink"
          >
            <Globe className="h-3.5 w-3.5" aria-hidden />
            <span>{lang.toUpperCase()}</span>
          </button>

          {/* Chọn bảng màu (Mặc định / Gruvbox) */}
          <PaletteMenu className="size-8 [&_svg]:size-4" />

          {/* Đổi theme sáng/tối */}
          <ThemeToggle className="size-8 [&_svg]:size-4" />

          {/* Menu mobile */}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="lp-mobile-nav"
            className="shrink-0 rounded-lg border border-line p-1.5 text-ink-muted hover:bg-paper-sunken hover:text-ink lg:hidden"
          >
            <span className="sr-only">{open ? ui.menuClose : ui.menuOpen}</span>
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" aria-hidden>
              {open ? <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" /> : <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />}
            </svg>
          </button>
        </div>
      </div>

      {open ? (
        <nav id="lp-mobile-nav" aria-label={ui.navAria} className="border-t border-line bg-paper-raised lg:hidden">
          <div className="lp-wrap flex flex-col py-3 text-[15px] font-medium text-ink">
            {content.NAV.map((n) => (
              <a key={n.href} href={n.href} onClick={() => setOpen(false)} className="py-2.5 hover:text-ember-strong">
                {n.label}
              </a>
            ))}

            <div className="mt-3 flex flex-col gap-2 border-t border-line pt-3 sm:hidden">
              <a href={studioHref} onClick={() => setOpen(false)} className="lp-btn lp-btn-ghost lp-btn-sm justify-center">
                {ui.openStudio}
              </a>
            </div>
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
