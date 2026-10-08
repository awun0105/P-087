"use client";

import { useEffect, useState } from "react";

import { listSamples } from "@/lib/api";
import type { SampleSummary } from "@/lib/types";

/**
 * Scene mẫu lấy trực tiếp từ API. Khi API không trả được dữ liệu, khối này ẩn hẳn
 * thay vì hiện "OFFLINE" hay "Đang nạp" làm người xem tưởng sản phẩm hỏng.
 */
export function LandingSamples({ title, lead, studioUrl }: { title: string; lead: string; studioUrl: string }) {
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
    <div className="mt-14 border-t border-line pt-10">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h3 className="text-lg font-bold text-ink">{title}</h3>
        <p className="text-[14px] text-ink-muted">{lead}</p>
      </div>
      <ul className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {samples.map((s) => (
          <li key={s.sample_id}>
            <a
              href={`${studioUrl}/new/try-demo?sample=${encodeURIComponent(s.sample_id)}`}
              className="group flex h-full flex-col rounded-xl border border-line bg-paper-raised p-5 transition-colors hover:border-line-strong"
            >
              <span className="font-mono text-[12px] text-geometry">
                {s.source.dataset} / {s.source.sequence}
                {s.frame_count ? `, ${s.frame_count} frame` : ""}
              </span>
              <span className="mt-2 text-[16px] font-bold text-ink">{s.title}</span>
              <span className="mt-1.5 text-[14px] leading-relaxed text-ink-muted">{s.description}</span>
              <span className="mt-auto pt-4 text-[14px] font-semibold text-ember-strong group-hover:underline">Mở scene mẫu</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
