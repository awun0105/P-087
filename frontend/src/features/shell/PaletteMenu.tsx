"use client";

import { Check, Palette as PaletteIcon } from "lucide-react";
import { useSyncExternalStore } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/shadcn/dropdown-menu";
import { Button } from "@/components/studio/primitives";
import { applyPalette, applyTheme, subscribeTheme, themeKey, type Palette, type Theme } from "@/lib/theme";
import { cn } from "@/lib/cn";

const PALETTES: { value: Palette; label: string; note: string; swatch: [string, string, string] }[] = [
  { value: "default", label: "Mặc định", note: "be + cam", swatch: ["#f5efe6", "#c2551f", "#2f7ea8"] },
  { value: "gruvbox", label: "Gruvbox", note: "vàng kem + cam đất", swatch: ["#fbf1c7", "#af3a03", "#076678"] },
];
const MODES: { value: Theme; label: string }[] = [
  { value: "light", label: "Sáng" },
  { value: "dark", label: "Tối" },
];

/**
 * Chọn giao diện (STUDIO_UX_SPEC.md D-17): bảng màu (mặc định hoặc Gruvbox) và chế độ sáng/tối. Trạng thái đọc từ
 * class trên <html> nên mọi menu trên trang luôn khớp nhau. Ô màu mẫu là màu cố định của từng bảng, để người dùng
 * thấy bảng kia trông thế nào trước khi chọn.
 */
export function PaletteMenu({ className }: { className?: string }) {
  const key = useSyncExternalStore(subscribeTheme, themeKey, () => "light:default");
  const [theme, palette] = key.split(":") as [Theme, Palette];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className={className} aria-label="Chọn giao diện" title="Chọn giao diện">
          <PaletteIcon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuLabel>Bảng màu</DropdownMenuLabel>
        {PALETTES.map((item) => (
          <DropdownMenuItem key={item.value} onSelect={() => applyPalette(item.value)} aria-current={palette === item.value}>
            <span className="flex overflow-hidden rounded-sm border border-line" aria-hidden>
              {item.swatch.map((color) => (
                <span key={color} className="size-3" style={{ background: color }} />
              ))}
            </span>
            <span className="flex-1">
              {item.label} <span className="text-ink-subtle">· {item.note}</span>
            </span>
            <Check className={cn("size-4", palette !== item.value && "invisible")} aria-hidden />
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Chế độ</DropdownMenuLabel>
        {MODES.map((item) => (
          <DropdownMenuItem key={item.value} onSelect={() => applyTheme(item.value)} aria-current={theme === item.value}>
            <span className="flex-1">{item.label}</span>
            <Check className={cn("size-4", theme !== item.value && "invisible")} aria-hidden />
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
