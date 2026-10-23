"use client";

import { useEffect, useState } from "react";

import { listSamples } from "@/lib/api";
import type { SampleSummary } from "@/lib/types";

/**
 * Scene mẫu lấy trực tiếp từ API. Khi API không trả được dữ liệu, khối này ẩn hẳn
 * thay vì hiện "OFFLINE" hay "Đang nạp" làm người xem tưởng sản phẩm hỏng.
 */
export function LandingSamples({
  title,
  lead,
  studioUrl,
  openLabel = "Mở scene mẫu",
}: {
  title: string;
  lead: string;
  studioUrl: string;
  openLabel?: string;
}) {
  const [samples, setSamples] = useState<SampleSummary[]>([]);

  useEffect(() => {
    let active = true;
    listSamples()
      .then((res) => {
        if (active && res.ok) setSamples(res.data.samples ?? []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  if (samples.length === 0) return null;

  return (
    <div className="lp-section-sub">
      <div className="lp-section-head">
        <h3 className="lp-h2">{title}</h3>
        <p>{lead}</p>
      </div>
      <ul className="lp-carousel mt-8">
        {samples.map((s) => (
          <li key={s.sample_id}>
            <a
              href={`${studioUrl}/new/try-demo?sample=${encodeURIComponent(s.sample_id)}`}
              className="lp-card group flex h-full flex-col transition-colors hover:border-line-strong"
            >
              <span className="lp-label">
                {s.source.dataset} / {s.source.sequence}
                {s.frame_count ? `, ${s.frame_count} frame` : ""}
              </span>
              <span className="mt-2 text-[16px] font-semibold text-ink">{s.title}</span>
              <span className="mt-1.5 text-[14px] leading-relaxed text-ink-muted">{s.description}</span>
              <span className="mt-auto pt-4 text-[14px] font-medium text-ink lp-link">
                {openLabel}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
