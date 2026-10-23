"use client";

import { useId, useState } from "react";

import { PROBLEM } from "@/features/landing/content";
import type { Language } from "@/lib/i18n";

/**
 * Hai sơ đồ mặt bằng chồng lên nhau với thanh kéo trước/sau: bản dựng từ video (một khối
 * điểm liền) và scene robot cần (từng vật có hộp va chạm, có thước mét).
 * Thanh kéo là một ô input kiểu range nên dùng được bằng bàn phím và trình đọc màn hình.
 * Là hình minh hoạ, không phải ảnh chụp kết quả.
 */

type Dot = { x: number; y: number; r: number; o: number };

function makeDots(): Dot[] {
  let seed = 11;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const areas = [
    { x0: 24, x1: 616, y0: 26, y1: 54, n: 140 },
    { x0: 24, x1: 616, y0: 126, y1: 154, n: 140 },
    { x0: 328, x1: 374, y0: 74, y1: 108, n: 22 },
    { x0: 10, x1: 630, y0: 54, y1: 126, n: 52 },
  ];
  const dots: Dot[] = [];
  for (const a of areas) {
    for (let i = 0; i < a.n; i++) {
      dots.push({
        x: a.x0 + rand() * (a.x1 - a.x0),
        y: a.y0 + rand() * (a.y1 - a.y0),
        r: 1.2 + rand() * 2.4,
        o: 0.3 + rand() * 0.5,
      });
    }
  }
  return dots;
}

const DOTS = makeDots();
const RACKS = [24, 94, 164, 234, 334, 404, 474, 544];

function Dots({ faded = false }: { faded?: boolean }) {
  return (
    <g fill="var(--studio-geometry)">
      {DOTS.map((d, i) => (
        <circle key={i} cx={d.x.toFixed(1)} cy={d.y.toFixed(1)} r={d.r.toFixed(1)} opacity={(faded ? d.o * 0.45 : d.o).toFixed(2)} />
      ))}
    </g>
  );
}

export function CompareScene({
  analogy = PROBLEM.analogy,
  lang = "vi",
}: {
  analogy?: typeof PROBLEM.analogy;
  lang?: Language;
}) {
  const { have, need } = analogy;
  const [pos, setPos] = useState(50);
  const id = useId();
  const palletLabel = "Pallet";
  const scanAria =
    lang === "en"
      ? "Raw 3D from video: aisle is an unstructured monolithic point cloud, cannot distinguish racks or pallets."
      : "Bản dựng từ video: cả lối đi là một đám điểm liền, không phân biệt kệ hay pallet.";
  const simAria =
    lang === "en"
      ? "Scene required by robots: each rack and pallet has dedicated collision hull, with 1-meter ruler."
      : "Scene robot cần: từng kệ và pallet là một vật riêng có hộp va chạm, kèm thước một mét.";
  const sliderLabel = lang === "en" ? "Compare: drag to reveal the robot-ready scene" : "So sánh: kéo để hiện scene robot cần";

  return (
    <div className="lp-compare" style={{ "--lp-pos": `${pos}%` } as React.CSSProperties}>
      <div className="lp-compare-stage">
        <svg viewBox="0 0 640 180" className="block h-auto w-full" role="img" aria-label={scanAria}>
          <Dots />
        </svg>
        <svg viewBox="0 0 640 180" className="lp-compare-after" role="img" aria-label={simAria}>
          <rect width="640" height="180" fill="var(--studio-viewport)" />
          <Dots faded />
          <g fill="none" stroke="var(--studio-ochre)" strokeWidth="1.5">
            {RACKS.map((x) => (
              <rect key={`t${x}`} x={x} y="26" width="62" height="28" rx="2" />
            ))}
            {RACKS.map((x) => (
              <rect key={`b${x}`} x={x} y="126" width="62" height="28" rx="2" />
            ))}
            <rect x="328" y="74" width="46" height="34" rx="2" strokeDasharray="4 3" />
          </g>
          <text x="382" y="94" className="lp-svg-label" fill="var(--studio-ochre)">{palletLabel}</text>
          <g stroke="var(--studio-on-dark)" strokeOpacity="0.8">
            <line x1="24" y1="168" x2="56" y2="168" />
            <line x1="24" y1="164" x2="24" y2="172" />
            <line x1="56" y1="164" x2="56" y2="172" />
          </g>
          <text x="62" y="172" className="lp-svg-label" fill="var(--studio-on-dark)">1 m</text>
        </svg>
        <div className="lp-compare-handle" aria-hidden>
          <span />
        </div>
        <span className="lp-compare-tag lp-compare-tag-left" aria-hidden>{have.label}</span>
        <span className="lp-compare-tag lp-compare-tag-right" aria-hidden>{need.label}</span>
        <input
          id={id}
          type="range"
          min={0}
          max={100}
          value={pos}
          onChange={(e) => setPos(Number(e.target.value))}
          aria-label={sliderLabel}
          className="lp-compare-range"
        />
      </div>
      <div className="lp-compare-captions">
        <div>
          <span className="lp-label">{have.label}, {have.like}</span>
          <span className="mt-1 block text-[15px] leading-snug text-ink">{have.body}</span>
        </div>
        <div>
          <span className="lp-label">{need.label}, {need.like}</span>
          <span className="mt-1 block text-[15px] leading-snug text-ink">{need.body}</span>
        </div>
      </div>
    </div>
  );
}
