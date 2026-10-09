/**
 * Ảnh minh hoạ tĩnh cho phần "scene trông như thế nào". Chưa có scene mẫu thật đạt yêu cầu,
 * nên thẻ nào cũng gắn nhãn "ảnh minh hoạ" để không ai tưởng đây là kết quả đã chạy.
 * Khi có scene mẫu thật: đổi `image` trong `SAMPLES.items` của content.ts, không phải sửa bố cục.
 */
export function LandingSamples({
  title,
  lead,
  badge,
  items,
  href,
  openLabel,
}: {
  title: string;
  lead: string;
  badge: string;
  items: readonly { image: string; title: string; body: string }[];
  href: string;
  openLabel: string;
}) {
  return (
    <section id="samples" className="lp-section">
      <div className="lp-wrap">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="lp-h2 text-ink">{title}</h2>
          <p className="text-[15px] text-ink-muted">{lead}</p>
        </div>
        <ul className="mt-8 grid gap-4 md:grid-cols-3">
          {items.map((it) => (
            <li key={it.image} className="flex flex-col overflow-hidden rounded-xl border border-line bg-paper-raised">
              <div className="relative">
                {/* eslint-disable-next-line @next/next/no-img-element -- ảnh SVG tĩnh, trang xuất static */}
                <img src={it.image} alt="" loading="lazy" className="block h-auto w-full" />
                <span className="absolute left-3 top-3 rounded border border-line-dark bg-viewport-deep px-1.5 py-0.5 font-mono text-[11px] text-on-dark/70">
                  {badge}
                </span>
              </div>
              <div className="flex flex-1 flex-col p-5">
                <p className="text-[16px] font-bold text-ink">{it.title}</p>
                <p className="mt-1.5 text-[14px] leading-relaxed text-ink-muted">{it.body}</p>
              </div>
            </li>
          ))}
        </ul>
        <a href={href} className="lp-btn lp-btn-ghost mt-8 inline-flex">
          {openLabel}
        </a>
      </div>
    </section>
  );
}
