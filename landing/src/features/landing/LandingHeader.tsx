"use client";

import { Check, Globe, Moon, Palette as PaletteIcon, Sun } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { getContent, getUiLabels } from "@/features/landing/content";
import { STUDIO_LOGIN_URL } from "@/lib/api";
import { applyLanguage, currentLanguage, subscribeLanguage, type Language } from "@/lib/i18n";
import { applyPalette, applyTheme, currentPalette, currentTheme, subscribeTheme, type Palette, type Theme } from "@/lib/theme";

const serverTheme = (): Theme => "light";
const serverPalette = (): Palette => "default";
const serverLang = (): Language => "vi";

const PALETTES: { value: Palette; swatch: [string, string, string] }[] = [
  { value: "default", swatch: ["#f5efe6", "#c2551f", "#2f7ea8"] },
  { value: "gruvbox", swatch: ["#fbf1c7", "#af3a03", "#076678"] },
];

export function LandingHeader({
  tryDemoHref,
  studioHref = STUDIO_LOGIN_URL,
}: {
  tryDemoHref: string;
  studioHref?: string;
}) {
  const [open, setOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const paletteMenuRef = useRef<HTMLDivElement>(null);

  const theme = useSyncExternalStore(subscribeTheme, currentTheme, serverTheme);
  const palette = useSyncExternalStore(subscribeTheme, currentPalette, serverPalette);
  const lang = useSyncExternalStore(subscribeLanguage, currentLanguage, serverLang);

  const content = getContent(lang);
  const ui = getUiLabels(lang);

  const nextTheme: Theme = theme === "dark" ? "light" : "dark";
  const themeLabel = theme === "dark" ? ui.themeLight : ui.themeDark;

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

  useEffect(() => {
    if (!paletteOpen) return;
    const onPointerDown = (e: MouseEvent) => {
      if (paletteMenuRef.current && !paletteMenuRef.current.contains(e.target as Node)) {
        setPaletteOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPaletteOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [paletteOpen]);

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
          <div ref={paletteMenuRef} className="relative inline-flex shrink-0">
            <button
              type="button"
              onClick={() => setPaletteOpen((v) => !v)}
              aria-label={ui.selectPalette}
              title={ui.selectPalette}
              aria-expanded={paletteOpen}
              aria-haspopup="menu"
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line text-ink-muted transition-colors hover:bg-paper-sunken hover:text-ink"
            >
              <PaletteIcon className="h-4 w-4" aria-hidden />
            </button>

            {paletteOpen && (
              <div
                role="menu"
                aria-label={ui.paletteTitle}
                className="absolute right-0 top-full mt-1.5 w-56 rounded-lg border border-line bg-paper-raised p-1 shadow-xl z-50 animate-in fade-in-0 zoom-in-95 duration-100"
              >
                <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                  {ui.paletteTitle}
                </div>
                {PALETTES.map((item) => {
                  const isSelected = palette === item.value;
                  const label = item.value === "default" ? ui.paletteDefault : ui.paletteGruvbox;
                  const note = item.value === "default" ? ui.paletteDefaultNote : ui.paletteGruvboxNote;
                  return (
                    <button
                      key={item.value}
                      type="button"
                      role="menuitem"
                      aria-current={isSelected}
                      onClick={() => {
                        applyPalette(item.value);
                        setPaletteOpen(false);
                      }}
                      className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-xs font-medium text-ink transition-colors hover:bg-paper-sunken"
                    >
                      <span className="flex shrink-0 overflow-hidden rounded-sm border border-line" aria-hidden>
                        {item.swatch.map((c) => (
                          <span key={c} className="h-3 w-3" style={{ background: c }} />
                        ))}
                      </span>
                      <span className="flex-1">
                        {label} <span className="text-ink-subtle">· {note}</span>
                      </span>
                      <Check className={`h-3.5 w-3.5 shrink-0 ${isSelected ? "text-ember-strong opacity-100" : "opacity-0"}`} aria-hidden />
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Đổi theme sáng/tối */}
          <button
            type="button"
            onClick={() => applyTheme(nextTheme)}
            aria-label={themeLabel}
            title={themeLabel}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line text-ink-muted transition-colors hover:bg-paper-sunken hover:text-ink"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
          </button>

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
