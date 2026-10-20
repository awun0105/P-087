"use client";

import { Check, Palette as PaletteIcon } from "lucide-react";
import { useSyncExternalStore } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/shadcn/dropdown-menu";
import { Button } from "@/components/studio/primitives";
import { applyPalette, subscribeTheme, themeKey, type Palette } from "@/lib/theme";
import { cn } from "@/lib/cn";

const PALETTES: { value: Palette; label: string; note: string; swatch: [string, string, string] }[] = [
  { value: "default", label: "Mặc định", note: "be + cam", swatch: ["#f5efe6", "#c2551f", "#2f7ea8"] },
  { value: "gruvbox", label: "Gruvbox", note: "vàng kem + cam đất", swatch: ["#fbf1c7", "#af3a03", "#076678"] },
];

/**
 * Chọn bảng màu: mặc định hoặc Gruvbox. Chế độ sáng/tối do nút `ThemeToggle` bên cạnh đảm
 * nhiệm (owner 02/10/2026: không lặp lại trong menu này). Trạng thái đọc từ class trên <html> nên mọi menu luôn khớp. Ô màu mẫu là màu cố định của từng bảng, để người dùng
 * thấy bảng kia trông thế nào trước khi chọn.
 */
export function PaletteMenu({ className }: { className?: string }) {
  const key = useSyncExternalStore(subscribeTheme, themeKey, () => "light:default");
  const palette = key.split(":")[1] as Palette;
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
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
