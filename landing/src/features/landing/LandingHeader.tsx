"use client";

import { ArrowRight, Check, Globe, Moon, Palette as PaletteIcon, Sun } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { getContent, getUiLabels } from "@/features/landing/content";
import { STUDIO_LOGIN_URL } from "@/lib/api";
import { applyLanguage, currentLanguage, subscribeLanguage, type Language } from "@/lib/i18n";
import Image from "next/image";
import { applyPalette, applyTheme, currentPalette, currentTheme, subscribeTheme, type Palette, type Theme } from "@/lib/theme";

const serverTheme = (): Theme => "dark";
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
      <div className="lp-wrap lp-header-row">
        <a href="#landing-top" className="lp-brand" aria-label={ui.brandAria}>
          <Image src="/icon.svg" alt="" width={26} height={26} aria-hidden="true" />
          <span>Real2Sim Studio</span>
        </a>

        <nav aria-label={ui.navAria} className="lp-nav">
          {content.NAV.map((n) => (
            <a key={n.href} href={n.href}>
              {n.label}
            </a>
          ))}
        </nav>

        <div className="lp-tools">
          <a href={studioHref} className="lp-btn lp-btn-ghost lp-btn-sm">
            {ui.openStudio}
          </a>
          <a href={tryDemoHref} className="lp-btn lp-btn-primary lp-btn-sm ml-1">
            {ui.tryDemo}
            <ArrowRight aria-hidden />
          </a>

          <div className="lp-tools-sep" aria-hidden />

          {/* Đổi ngôn ngữ */}
          <button type="button" onClick={() => applyLanguage(nextLang)} aria-label={langLabel} title={langLabel} className="lp-icon-btn">
            <Globe aria-hidden />
            <span>{lang.toUpperCase()}</span>
          </button>

          {/* Chọn bảng màu (Mặc định / Gruvbox) */}
          <div ref={paletteMenuRef} className="relative inline-flex">
            <button
              type="button"
              onClick={() => setPaletteOpen((v) => !v)}
              aria-label={ui.selectPalette}
              title={ui.selectPalette}
              aria-expanded={paletteOpen}
              aria-haspopup="menu"
              className="lp-icon-btn"
            >
              <PaletteIcon aria-hidden />
            </button>

            {paletteOpen && (
              <div role="menu" aria-label={ui.paletteTitle} className="lp-menu">
                <div className="lp-menu-title">{ui.paletteTitle}</div>
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
                      className="lp-menu-item"
                    >
                      <span className="lp-swatch" aria-hidden>
                        {item.swatch.map((c) => (
                          <span key={c} style={{ background: c }} />
                        ))}
                      </span>
                      <span className="flex-1">
                        {label}
                        <small>{note}</small>
                      </span>
                      <Check className={`h-3.5 w-3.5 shrink-0 text-ink ${isSelected ? "opacity-100" : "opacity-0"}`} aria-hidden />
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Đổi theme sáng/tối */}
          <button type="button" onClick={() => applyTheme(nextTheme)} aria-label={themeLabel} title={themeLabel} className="lp-icon-btn">
            {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
          </button>

          {/* Menu mobile */}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="lp-mobile-nav"
            className="lp-icon-btn lp-menu-btn"
          >
            <span className="sr-only">{open ? ui.menuClose : ui.menuOpen}</span>
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.75" aria-hidden>
              {open ? <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" /> : <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />}
            </svg>
          </button>
        </div>
      </div>

      {open ? (
        <nav id="lp-mobile-nav" aria-label={ui.navAria} className="lp-mobile-nav">
          <div className="lp-wrap flex flex-col py-3">
            {content.NAV.map((n) => (
              <a key={n.href} href={n.href} onClick={() => setOpen(false)}>
                {n.label}
              </a>
            ))}

            <div className="mt-3 flex flex-col gap-2 border-t border-line pt-4 sm:hidden">
              <a href={tryDemoHref} onClick={() => setOpen(false)} className="lp-btn lp-btn-primary">
                {ui.tryDemo}
              </a>
              <a href={studioHref} onClick={() => setOpen(false)} className="lp-btn lp-btn-ghost">
                {ui.openStudio}
              </a>
            </div>
          </div>
        </nav>
      ) : null}
    </header>
  );
}
