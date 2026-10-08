import { HERO, HERO_CHAIN } from "@/features/landing/content";

/**
 * Sơ đồ mặt bằng một lối đi trong kho, nhìn từ trên xuống: chấm Gaussian (Visual),
 * lưới mét (Geometry), hộp collider (Physics) và đường Start–Goal của robot.
 * Là hình minh hoạ luồng xử lý, không phải ảnh chụp kết quả (UX spec D-05).
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

export function HeroScene() {
  return (
    <figure className="lp-viewport">
      <div className="flex items-center justify-between gap-3 border-b border-line-dark px-4 py-2.5">
        <span className="font-mono text-[12px] text-on-dark/70">{HERO.sceneLabel}</span>
        <span className="hidden gap-1.5 sm:flex" aria-hidden>
          {HERO.pillars.map((p) => (
            <span key={p} className="rounded border border-line-dark px-1.5 py-0.5 font-mono text-[11px] text-on-dark/60">
              {p}
            </span>
          ))}
        </span>
      </div>

      <svg viewBox="0 0 560 360" className="block h-auto w-full" role="img" aria-labelledby="hero-scene-title">
        <title id="hero-scene-title">
          Sơ đồ mặt bằng lối đi trong kho: hai dãy kệ và một pallet có hộp va chạm, lưới một mét, và đường đi của robot từ Start tới Goal vòng qua pallet.
        </title>

        {/* Lưới mét */}
        <g stroke="var(--studio-on-dark)" strokeOpacity="0.07">
          {Array.from({ length: 15 }, (_, i) => (
            <line key={`v${i}`} x1={i * 40} y1="0" x2={i * 40} y2="360" />
          ))}
          {Array.from({ length: 10 }, (_, i) => (
            <line key={`h${i}`} x1="0" y1={i * 40} x2="560" y2={i * 40} />
          ))}
        </g>

        {/* Visual: chấm Gaussian */}
        <g fill="var(--studio-geometry)">
          {DOTS.map((d, i) => (
            <circle key={i} cx={d.x.toFixed(1)} cy={d.y.toFixed(1)} r={d.r.toFixed(1)} opacity={d.o.toFixed(2)} />
          ))}
        </g>

        {/* Physics: collider của kệ và pallet */}
        <g fill="none" stroke="var(--studio-ochre)" strokeWidth="1.5">
          {BAYS.map((x) => (
            <rect key={`t${x}`} x={x} y="60" width="112" height="40" rx="2" />
          ))}
          {BAYS.map((x) => (
            <rect key={`b${x}`} x={x} y="260" width="112" height="40" rx="2" />
          ))}
          <rect x="300" y="148" width="60" height="50" rx="2" strokeDasharray="5 4" />
        </g>
        <text x="300" y="140" className="lp-svg-label" fill="var(--studio-ochre)">
          Object_004 · collider
        </text>

        {/* Đường đi Start → Goal vòng qua pallet */}
        <path
          className="lp-route"
          d="M 72 180 C 160 180, 230 226, 300 226 S 400 222, 430 200 S 480 180, 496 180"
          fill="none"
          stroke="var(--studio-sage)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <rect x="56" y="168" width="30" height="24" rx="4" fill="var(--studio-sage)" fillOpacity="0.2" stroke="var(--studio-sage)" />
        <text x="54" y="160" className="lp-svg-label" fill="var(--studio-on-dark)">Start</text>
        <circle cx="496" cy="180" r="7" fill="none" stroke="var(--studio-sage)" strokeWidth="2" />
        <circle cx="496" cy="180" r="2.5" fill="var(--studio-sage)" />
        <text x="482" y="160" className="lp-svg-label" fill="var(--studio-on-dark)">Goal</text>

        {/* Thước tỉ lệ: một ô lưới là một mét */}
        <g stroke="var(--studio-on-dark)" strokeOpacity="0.8">
          <line x1="40" y1="336" x2="80" y2="336" />
          <line x1="40" y1="331" x2="40" y2="341" />
          <line x1="80" y1="331" x2="80" y2="341" />
        </g>
        <text x="88" y="340" className="lp-svg-label" fill="var(--studio-on-dark)">1 m</text>
      </svg>

      <ol className="grid grid-cols-2 gap-px border-t border-line-dark bg-line-dark sm:grid-cols-5">
        {HERO_CHAIN.map((c, i) => (
          <li key={c.label} className="bg-viewport-deep px-3 py-3" data-tone={c.tone}>
            <span className="font-mono text-[11px] text-on-dark/50">{String(i + 1).padStart(2, "0")}</span>
            <span className="lp-chain-label mt-0.5 block text-[13px] font-semibold">{c.label}</span>
            <span className="mt-0.5 block text-[12px] leading-snug text-on-dark/60">{c.detail}</span>
          </li>
        ))}
      </ol>
      <figcaption className="px-4 py-2 text-[12px] text-on-dark/50">Sơ đồ minh hoạ luồng xử lý, không phải ảnh chụp kết quả.</figcaption>
    </figure>
  );
}
