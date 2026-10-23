"use client";

import { useEffect, useState } from "react";

/** Cụm chữ xoay vòng ở Hero: mỗi 2,8 giây đổi sang cụm tiếp theo, trượt lên như trang tham chiếu. */
export function RotatingText({ items, interval = 2800 }: { items: readonly string[]; interval?: number }) {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (items.length < 2) return;
    const reduced = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return;
    const t = window.setInterval(() => setIndex((i) => (i + 1) % items.length), interval);
    return () => window.clearInterval(t);
  }, [items.length, interval]);
  const prev = (index - 1 + items.length) % items.length;
  return (
    <span className="lp-rotator" aria-live="polite" aria-atomic="true">
      {items.map((t, i) => (
        <span key={t} data-active={i === index} data-leaving={items.length > 1 && i === prev} aria-hidden={i !== index}>
          {t}
        </span>
      ))}
    </span>
  );
}
