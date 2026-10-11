"use client";

import { LockKeyhole } from "lucide-react";
import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import type { Tab } from "@/features/studio/scene/state";
import { cn } from "@/lib/cn";

export interface SceneTabItem {
  id: Tab;
  label: string;
  icon: ReactNode;
  locked: string | null;
}

/** Tab khóa vẫn đọc được bằng keyboard/chạm; không dùng tooltip làm lời giải thích duy nhất. */
export function SceneTabs({ tabs, current, onChange }: { tabs: SceneTabItem[]; current: Tab; onChange: (tab: Tab) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const [reason, setReason] = useState<string | null>(null);

  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
      : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
        : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    refs.current[next]?.focus();
  }

  return (
    <div className="border-b border-line bg-paper">
      <nav role="tablist" aria-label="Vùng của scene" className="flex gap-1 overflow-x-auto px-4 py-2 [scrollbar-width:none] sm:px-6">
        {tabs.map((item, index) => (
          <button
            key={item.id}
            ref={(node) => { refs.current[index] = node; }}
            type="button"
            id={`scene-tab-${item.id}`}
            role="tab"
            aria-selected={current === item.id}
            aria-disabled={item.locked !== null}
            aria-controls={`scene-panel-${item.id}`}
            aria-label={item.locked ? `${item.label}: ${item.locked}` : item.label}
            tabIndex={current === item.id ? 0 : -1}
            onKeyDown={(event) => navigate(event, index)}
            onFocus={() => setReason(item.locked ? `${item.label}: ${item.locked}.` : null)}
            onClick={() => {
              if (item.locked) setReason(`${item.label}: ${item.locked}.`);
              else { setReason(null); onChange(item.id); }
            }}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember [&_svg]:size-4",
              current === item.id ? "bg-ember-soft font-medium text-ember-strong" : "text-ink-muted hover:bg-paper-sunken hover:text-ink",
              item.locked && "text-ink-subtle",
            )}
          >
            {item.icon} {item.label}
            {item.locked && <LockKeyhole className="size-3" aria-hidden />}
          </button>
        ))}
      </nav>
      {reason && <p role="status" className="px-4 pb-2 text-xs text-ink-muted sm:px-6">{reason}</p>}
    </div>
  );
}
