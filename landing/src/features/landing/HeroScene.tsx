"use client";

import { useState } from "react";

import { HERO, HERO_CHAIN } from "@/features/landing/content";
import type { Language } from "@/lib/i18n";

/**
 * Sơ đồ mặt bằng một lối đi trong kho, nhìn từ trên xuống: chấm Gaussian (Visual),
 * lưới mét (Geometry), hộp collider (Physics) và đường Start–Goal của robot.
 * Là hình minh hoạ luồng xử lý, không phải ảnh chụp kết quả (UX spec D-05).
 *
 * Tương tác: ba lớp hiện dần khi tải, robot chạy dọc đường đi; bấm nút lớp
 * ở thanh trên để bật tắt từng lớp, đúng như cách Studio cho xem từng lớp.
 */

// Chấm Gaussian giả lập, sinh tất định để server và client render giống nhau.
function gaussianDots() {
  let seed = 7;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const bands = [
    { y0: 52, y1: 108 },
    { y0: 252, y1: 308 },
    { y0: 140, y1: 205, x0: 292, x1: 368 },
  ];
  const dots: { x: number; y: number; r: number; o: number }[] = [];
  for (const b of bands) {
    const n = b.x0 ? 40 : 110;
    for (let i = 0; i < n; i++) {
      const x0 = b.x0 ?? 36;
      const x1 = b.x1 ?? 524;
      dots.push({
        x: x0 + rand() * (x1 - x0),
        y: b.y0 + rand() * (b.y1 - b.y0),
        r: 1.2 + rand() * 2.6,
        o: 0.25 + rand() * 0.5,
      });
    }
  }
  return dots;
}

const DOTS = gaussianDots();
const BAYS = [40, 160, 280, 400];
const ROUTE = "M 72 180 C 160 180, 230 226, 300 226 S 400 222, 430 200 S 480 180, 496 180";
const LAYER_KEYS = ["visual", "geometry", "physics"] as const;
type LayerKey = (typeof LAYER_KEYS)[number];

export function HeroScene({
  hero = HERO,
  heroChain = HERO_CHAIN,
  lang = "vi",
}: {
  hero?: typeof HERO;
  heroChain?: readonly { label: string; detail: string; tone: string }[];
  lang?: Language;
}) {
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({ visual: true, geometry: true, physics: true });
  const toggle = (k: LayerKey) => setLayers((s) => ({ ...s, [k]: !s[k] }));

  const svgTitle =
    lang === "en"
      ? "Top-down layout diagram of warehouse aisle: two rack rows, pallet with collision hull, metric grid, and Start-to-Goal path around the obstacle."
      : "Sơ đồ mặt bằng lối đi trong kho: hai dãy kệ và một pallet có hộp va chạm, lưới một mét, và đường đi của robot từ Start tới Goal vòng qua pallet.";
  const caption =
    lang === "en"
      ? "Pipeline schematic diagram, not rendered result. Click a layer name to show or hide it."
      : "Sơ đồ minh hoạ luồng xử lý, không phải ảnh chụp kết quả. Bấm tên lớp để bật hoặc tắt.";
  const layerAria = (k: LayerKey, on: boolean) =>
    lang === "en" ? `${on ? "Hide" : "Show"} ${k} layer` : `${on ? "Ẩn" : "Hiện"} lớp ${k}`;

  return (
    <figure className="lp-viewport">
      <div className="lp-viewport-bar">
        <span>{hero.sceneLabel}</span>
        <span className="lp-viewport-pills" role="group" aria-label={lang === "en" ? "Layers" : "Các lớp"}>
          {hero.pillars.map((p, i) => {
            const k = LAYER_KEYS[i] ?? "visual";
            const on = layers[k];
            return (
              <button key={p} type="button" aria-pressed={on} aria-label={layerAria(k, on)} data-tone={k} onClick={() => toggle(k)}>
                <span className="lp-pill-dot" aria-hidden />
                {p}
              </button>
            );
          })}
        </span>
      </div>

      <svg viewBox="0 0 560 360" className="lp-scene block h-auto w-full" role="img" aria-labelledby="hero-scene-title">
        <title id="hero-scene-title">{svgTitle}</title>

        {/* Geometry: lưới mét + thước */}
        <g className="lp-scene-layer" data-on={layers.geometry} style={{ "--lp-order": 1 } as React.CSSProperties}>
          <g stroke="var(--studio-on-dark)" strokeOpacity="0.07">
            {Array.from({ length: 15 }, (_, i) => (
              <line key={`v${i}`} x1={i * 40} y1="0" x2={i * 40} y2="360" />
            ))}
            {Array.from({ length: 10 }, (_, i) => (
              <line key={`h${i}`} x1="0" y1={i * 40} x2="560" y2={i * 40} />
            ))}
          </g>
          <g stroke="var(--studio-on-dark)" strokeOpacity="0.8">
            <line x1="40" y1="336" x2="80" y2="336" />
            <line x1="40" y1="331" x2="40" y2="341" />
            <line x1="80" y1="331" x2="80" y2="341" />
          </g>
          <text x="88" y="340" className="lp-svg-label" fill="var(--studio-on-dark)">1 m</text>
        </g>

        {/* Visual: chấm Gaussian */}
        <g className="lp-scene-layer" data-on={layers.visual} style={{ "--lp-order": 0 } as React.CSSProperties} fill="var(--studio-geometry)">
          {DOTS.map((d, i) => (
            <circle key={i} cx={d.x.toFixed(1)} cy={d.y.toFixed(1)} r={d.r.toFixed(1)} opacity={d.o.toFixed(2)} />
          ))}
        </g>

        {/* Physics: collider của kệ và pallet */}
        <g className="lp-scene-layer" data-on={layers.physics} style={{ "--lp-order": 2 } as React.CSSProperties}>
          <g fill="none" stroke="var(--studio-ochre)" strokeWidth="1.5">
            {BAYS.map((x) => (
              <rect key={`t${x}`} x={x} y="60" width="112" height="40" rx="2" />
            ))}
            {BAYS.map((x) => (
              <rect key={`b${x}`} x={x} y="260" width="112" height="40" rx="2" />
            ))}
            <rect className="lp-pallet" x="300" y="148" width="60" height="50" rx="2" strokeDasharray="5 4" />
          </g>
          <text x="300" y="140" className="lp-svg-label" fill="var(--studio-ochre)">
            Object_004 collider
          </text>
        </g>

        {/* Đường đi Start → Goal vòng qua pallet, rồi robot chạy theo */}
        <g className="lp-scene-layer" style={{ "--lp-order": 3 } as React.CSSProperties}>
          <path className="lp-route" d={ROUTE} fill="none" stroke="var(--studio-sage)" strokeWidth="2.5" strokeLinecap="round" />
          <rect x="56" y="168" width="30" height="24" rx="4" fill="var(--studio-sage)" fillOpacity="0.2" stroke="var(--studio-sage)" />
          <text x="54" y="160" className="lp-svg-label" fill="var(--studio-on-dark)">Start</text>
          <circle className="lp-goal-ring" cx="496" cy="180" r="7" fill="none" stroke="var(--studio-sage)" strokeWidth="2" />
          <circle cx="496" cy="180" r="2.5" fill="var(--studio-sage)" />
          <text x="482" y="160" className="lp-svg-label" fill="var(--studio-on-dark)">Goal</text>
          <g className="lp-robot" style={{ offsetPath: `path("${ROUTE}")` } as React.CSSProperties}>
            <circle r="9" fill="var(--studio-sage)" fillOpacity="0.25" />
            <circle r="4.5" fill="var(--studio-sage)" />
          </g>
        </g>
      </svg>

      <ol className="lp-chain">
        {heroChain.map((c, i) => (
          <li key={c.label} data-tone={c.tone} style={{ "--lp-order": i } as React.CSSProperties}>
            <span className="lp-chain-step">{String(i + 1).padStart(2, "0")}</span>
            <span className="lp-chain-label">{c.label}</span>
            <span className="lp-chain-detail">{c.detail}</span>
          </li>
        ))}
      </ol>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}
