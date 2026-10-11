"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/studio/primitives";
import { applyTheme, currentTheme, subscribeTheme, type Theme } from "@/lib/theme";

const serverTheme = (): Theme => "light";

/** Nút đổi theme sáng/tối; trạng thái đọc từ class trên <html> nên mọi nút trên trang luôn khớp nhau. */
export function ThemeToggle({ className }: { className?: string }) {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, serverTheme);
  const next: Theme = theme === "dark" ? "light" : "dark";
  const label = next === "dark" ? "Chuyển sang giao diện tối" : "Chuyển sang giao diện sáng";
  return (
    <Button variant="ghost" size="icon" className={className} aria-label={label} title={label} onClick={() => applyTheme(next)}>
      {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
    </Button>
  );
}
