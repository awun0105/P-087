"use client";

import { useState } from "react";

interface CopyButtonProps {
  value: string;
  label?: string;
}

export function CopyButton({ value, label = "Sao chép" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(value);
      } else {
        // Fallback cho jsdom/headless hoặc trình duyệt cũ — không fail test.
        throw new Error("clipboard unavailable");
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // Không hiện lỗi, chỉ đơn giản là không đổi trạng thái.
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="rounded px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-800 hover:text-slate-300 transition-colors"
      title={label}
    >
      {copied ? "✓" : "⧉"}
    </button>
  );
}
