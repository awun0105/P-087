import { PROBLEM } from "@/features/landing/content";

/**
 * Hai sơ đồ mặt bằng cạnh nhau: bản dựng từ video (một khối điểm liền) và scene robot cần
 * (từng vật có hộp va chạm, có thước mét). Là hình minh hoạ, không phải ảnh chụp kết quả.
 */

type Dot = { x: number; y: number; r: number; o: number };

function makeDots(): Dot[] {
  let seed = 11;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const areas = [
    { x0: 24, x1: 296, y0: 26, y1: 54, n: 70 },
    { x0: 24, x1: 296, y0: 126, y1: 154, n: 70 },
    { x0: 168, x1: 214, y0: 74, y1: 108, n: 22 },
    { x0: 10, x1: 310, y0: 54, y1: 126, n: 26 },
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
const RACKS = [24, 94, 164, 234];

function Dots({ faded = false }: { faded?: boolean }) {
  return (
    <g fill="var(--studio-geometry)">
      {DOTS.map((d, i) => (
        <circle key={i} cx={d.x.toFixed(1)} cy={d.y.toFixed(1)} r={d.r.toFixed(1)} opacity={(faded ? d.o * 0.45 : d.o).toFixed(2)} />
      ))}
    </g>
  );
}

export function CompareScene() {
  const { have, need } = PROBLEM.analogy;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <figure className="lp-compare">
        <svg viewBox="0 0 320 180" className="block h-auto w-full" role="img" aria-label="Bản dựng từ video: cả lối đi là một đám điểm liền, không phân biệt kệ hay pallet.">
          <Dots />
        </svg>
        <figcaption className="lp-compare-caption">
          <span className="text-[13px] text-ink-muted">{have.label}, {have.like}</span>
          <span className="mt-1 block text-[15px] leading-snug text-ink">{have.body}</span>
        </figcaption>
      </figure>

      <figure className="lp-compare">
        <svg viewBox="0 0 320 180" className="block h-auto w-full" role="img" aria-label="Scene robot cần: từng kệ và pallet là một vật riêng có hộp va chạm, kèm thước một mét.">
          <Dots faded />
          <g fill="none" stroke="var(--studio-ochre)" strokeWidth="1.5">
            {RACKS.map((x) => (
              <rect key={`t${x}`} x={x} y="26" width="62" height="28" rx="2" />
            ))}
            {RACKS.map((x) => (
              <rect key={`b${x}`} x={x} y="126" width="62" height="28" rx="2" />
            ))}
            <rect x="168" y="74" width="46" height="34" rx="2" strokeDasharray="4 3" />
          </g>
          <text x="28" y="20" className="lp-svg-label" fill="var(--studio-on-dark)">Kệ</text>
          <text x="222" y="94" className="lp-svg-label" fill="var(--studio-ochre)">Pallet</text>
          <g stroke="var(--studio-on-dark)" strokeOpacity="0.8">
            <line x1="24" y1="168" x2="56" y2="168" />
            <line x1="24" y1="164" x2="24" y2="172" />
            <line x1="56" y1="164" x2="56" y2="172" />
          </g>
          <text x="62" y="172" className="lp-svg-label" fill="var(--studio-on-dark)">1 m</text>
        </svg>
        <figcaption className="lp-compare-caption">
          <span className="text-[13px] text-ink-muted">{need.label}, {need.like}</span>
          <span className="mt-1 block text-[15px] leading-snug text-ink">{need.body}</span>
        </figcaption>
      </figure>
    </div>
  );
}
