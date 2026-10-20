"use client";

import { useEffect, useState } from "react";
import { Cpu, Loader2 } from "lucide-react";

import { Notice } from "@/components/studio/primitives";
import type { GpuCapacity } from "@/lib/api/gpu";

/** "khoảng 12 phút" / "dưới 1 phút" — always rounded up so the wait is never understated. */
export function formatWait(seconds: number): string {
  if (seconds < 60) return "dưới 1 phút";
  return `khoảng ${Math.ceil(seconds / 60)} phút`;
}

/** Elapsed and remaining seconds of a cold start, counted locally from `since` (no polling needed). */
export function startupProgress(capacity: GpuCapacity, nowMs: number): { elapsed: number; remaining: number; ratio: number } {
  const expected = Math.max(1, capacity.expected_startup_seconds);
  const started = capacity.since ? Date.parse(capacity.since) : NaN;
  const elapsed = Number.isFinite(started) ? Math.max(0, Math.floor((nowMs - started) / 1000)) : capacity.elapsed_seconds ?? 0;
  const remaining = Math.max(0, expected - elapsed);
  return { elapsed, remaining, ratio: Math.min(1, elapsed / expected) };
}

/**
 * Tells a waiting user that a GPU is being rented and how long it usually takes, so a cold start
 * (image pull + worker check, ~10–15 min) does not look like a hung app. Renders nothing when a GPU
 * is ready or GPUs are not managed here. The parent passes `capacity`; this component never polls.
 */
export function GpuStartupNotice({ capacity, now, className }: { capacity: GpuCapacity | null | undefined; now?: number; className?: string }) {
  const [tick, setTick] = useState(() => Date.now());
  const counting = capacity?.state === "starting" && now === undefined;
  useEffect(() => {
    if (!counting) return;
    const timer = window.setInterval(() => setTick(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [counting]);

  if (!capacity) return null;
  const nowMs = now ?? tick;
  const typical = formatWait(capacity.expected_startup_seconds);

  if (capacity.state === "off") {
    return (
      <Notice tone="neutral" className={className} icon={<Cpu aria-hidden />}>
        Máy GPU đang tắt để tiết kiệm chi phí. Hệ thống sẽ tự bật máy cho việc này; lần khởi động thường mất {typical}.
      </Notice>
    );
  }
  if (capacity.state === "starting") {
    const { elapsed, remaining, ratio } = startupProgress(capacity, nowMs);
    return (
      <Notice tone="ember" className={className} icon={<Loader2 className="animate-spin" aria-hidden />}>
        <span className="block font-medium">Đang khởi động máy GPU</span>
        <span className="block">
          {remaining > 0
            ? `Còn ${formatWait(remaining)} (đã chờ ${formatWait(elapsed).replace("khoảng ", "")}).`
            : "Sắp xong, máy đang chạy bước tự kiểm cuối."}{" "}
          Việc của bạn đã vào hàng đợi và sẽ tự chạy ngay khi máy sẵn sàng; không cần giữ trang này mở.
        </span>
        <span
          role="progressbar"
          aria-label="Tiến độ khởi động máy GPU"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(ratio * 100)}
          className="mt-2 block h-1.5 w-full overflow-hidden rounded-full bg-line-strong"
        >
          <span className="block h-full rounded-full bg-current transition-[width] duration-700" style={{ width: `${Math.round(ratio * 100)}%` }} />
        </span>
      </Notice>
    );
  }
  if (capacity.state === "draining") {
    return (
      <Notice tone="neutral" className={className} icon={<Cpu aria-hidden />}>
        Máy GPU đang hoàn tất việc trước rồi tắt. Việc mới sẽ được nhận ở lần bật kế tiếp, thường mất {typical}.
      </Notice>
    );
  }
  if (capacity.state === "blocked") {
    return (
      <Notice tone="rust" className={className} icon={<Cpu aria-hidden />}>
        Chưa thuê được máy GPU (hết máy phù hợp hoặc chạm giới hạn chi phí). Việc vẫn nằm trong hàng đợi; quản trị viên cần kiểm tra.
      </Notice>
    );
  }
  return null;
}
