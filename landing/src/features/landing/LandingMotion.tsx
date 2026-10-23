"use client";

import { useEffect, type ReactNode } from "react";

/**
 * Chuyển động của landing, tất cả dựa trên cuộn và thao tác người dùng:
 * - mục có `data-reveal` hiện dần một lần khi vào khung nhìn;
 * - menu tô sáng mục đang xem; header đổ bóng khi cuộn;
 * - đường tiến trình ở phần Quy trình tự vẽ theo vị trí cuộn.
 * Không có JavaScript hoặc không có IntersectionObserver thì mọi thứ hiện sẵn.
 */
export function LandingMotion() {
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const reduced = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return;

    const root = document.documentElement;
    root.classList.add("lp-js");

    // 1. Hiện dần
    const revealIo = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            revealIo.unobserve(e.target);
          }
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.1 },
    );
    document.querySelectorAll<HTMLElement>(".landing-page [data-reveal]").forEach((el) => revealIo.observe(el));

    // 2. Menu theo mục đang xem
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>('.lp-nav a[href^="#"]'));
    const sections = links
      .map((a) => document.getElementById(a.hash.slice(1)))
      .filter((s): s is HTMLElement => s !== null);
    const setActive = (id: string | null) => {
      for (const a of links) {
        if (a.hash.slice(1) === id) a.setAttribute("aria-current", "true");
        else a.removeAttribute("aria-current");
      }
    };
    const visible = new Map<Element, number>();
    const spyIo = new IntersectionObserver(
      (entries) => {
        for (const e of entries) visible.set(e.target, e.isIntersecting ? e.intersectionRatio : 0);
        let best: Element | null = null;
        let bestRatio = 0;
        for (const [el, r] of visible) {
          if (r > bestRatio) {
            best = el;
            bestRatio = r;
          }
        }
        setActive(best ? best.id : null);
      },
      { rootMargin: "-40% 0px -50% 0px", threshold: [0, 0.1, 0.25, 0.5] },
    );
    sections.forEach((s) => spyIo.observe(s));

    // 3. Header đổ bóng, đường tiến trình tự vẽ
    const header = document.querySelector<HTMLElement>(".lp-header");
    const timeline = document.querySelector<HTMLElement>(".lp-timeline");
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        header?.classList.toggle("is-scrolled", window.scrollY > 8);
        if (timeline) {
          const r = timeline.getBoundingClientRect();
          const anchor = window.innerHeight * 0.6;
          const p = Math.min(1, Math.max(0, (anchor - r.top) / r.height));
          timeline.style.setProperty("--lp-progress", p.toFixed(3));
        }
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);

    return () => {
      revealIo.disconnect();
      spyIo.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
      root.classList.remove("lp-js");
    };
  }, []);
  return null;
}

/** Bọc một khối để nó hiện dần khi cuộn tới. `delay` tính theo bậc 80ms. */
export function Reveal({ children, delay = 0, className = "", as: Tag = "div" }: { children: ReactNode; delay?: number; className?: string; as?: "div" | "section" | "li" | "article" }) {
  return (
    <Tag data-reveal className={className} style={delay ? ({ "--lp-delay": `${delay * 80}ms` } as React.CSSProperties) : undefined}>
      {children}
    </Tag>
  );
}
