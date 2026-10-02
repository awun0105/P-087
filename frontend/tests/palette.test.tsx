/** Bảng màu (D-17): chọn và lưu bảng màu, độ tương phản của bốn biến thể, và không còn mã màu viết cứng trong UI. */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PaletteMenu } from "@/features/shell/PaletteMenu";
import { ThemeToggle } from "@/features/shell/ThemeToggle";
import {
  PALETTE_STORAGE_KEY,
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
  applyPalette,
  applyTheme,
  currentPalette,
  themeColor,
  themeKey,
} from "@/lib/theme";

afterEach(() => {
  cleanup();
  document.documentElement.classList.remove("dark", "theme-gruvbox");
  document.documentElement.removeAttribute("style");
  window.localStorage.clear();
});

describe("chọn bảng màu", () => {
  it("mặc định là bảng hiện tại; chọn Gruvbox thì gắn class và lưu, độc lập với sáng/tối", () => {
    expect(currentPalette()).toBe("default");
    applyPalette("gruvbox");
    expect(document.documentElement.classList.contains("theme-gruvbox")).toBe(true);
    expect(window.localStorage.getItem(PALETTE_STORAGE_KEY)).toBe("gruvbox");
    applyTheme("dark");
    expect(themeKey()).toBe("dark:gruvbox");
    applyPalette("default");
    expect(themeKey()).toBe("dark:default"); // đổi bảng màu không đụng chế độ tối
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("script khởi tạo khôi phục cả bảng màu lẫn chế độ trước lần vẽ đầu", () => {
    new Function(THEME_INIT_SCRIPT)();
    expect(themeKey()).toBe("light:default");
    window.localStorage.setItem(PALETTE_STORAGE_KEY, "gruvbox");
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(THEME_INIT_SCRIPT)();
    expect(themeKey()).toBe("dark:gruvbox");
    window.localStorage.setItem(PALETTE_STORAGE_KEY, "khong-co");
    document.documentElement.classList.remove("theme-gruvbox");
    new Function(THEME_INIT_SCRIPT)();
    expect(currentPalette()).toBe("default"); // giá trị lạ thì giữ bảng mặc định
  });

  it("menu chọn giao diện đổi bảng màu và chế độ, và khớp với nút sáng/tối", () => {
    render(<><PaletteMenu /><ThemeToggle /></>);
    const trigger = screen.getByRole("button", { name: "Chọn giao diện" });
    fireEvent.keyDown(trigger, { key: "Enter" });
    fireEvent.click(screen.getByRole("menuitem", { name: /Gruvbox/ }));
    expect(currentPalette()).toBe("gruvbox");
    fireEvent.keyDown(screen.getByRole("button", { name: "Chọn giao diện" }), { key: "Enter" });
    expect(screen.getByRole("menuitem", { name: /Gruvbox/ })).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("menuitem", { name: "Tối" }));
    expect(themeKey()).toBe("dark:gruvbox");
    expect(screen.getByRole("button", { name: "Chuyển sang giao diện sáng" })).toBeInTheDocument();
  });

  it("themeColor đọc biến đang hiệu lực, thiếu thì dùng giá trị dự phòng", () => {
    expect(themeColor("--studio-sage", "#5e8c61")).toBe("#5e8c61");
    document.documentElement.style.setProperty("--studio-sage", "#79740e");
    expect(themeColor("--studio-sage", "#5e8c61")).toBe("#79740e");
  });
});

const CSS = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");

function variables(selector: string): Record<string, string> {
  const start = CSS.indexOf(selector);
  expect(start, `không thấy khối ${selector}`).toBeGreaterThanOrEqual(0);
  const body = CSS.slice(start, CSS.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((match) => [match[1], match[2]]));
}

function luminance(hex: string): number {
  const channel = (index: number) => {
    const value = parseInt(hex.slice(index, index + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

describe("bốn biến thể giao diện đều đủ tương phản (WCAG)", () => {
  const defaultLight = variables(":root,\n.landing-page {");
  const gruvboxLight = variables(".theme-gruvbox,\n.theme-gruvbox .landing-page {");
  const variants: Record<string, Record<string, string>> = {
    "mặc định sáng": defaultLight,
    "mặc định tối": { ...defaultLight, ...variables(".dark {\n  --studio-paper") },
    "Gruvbox sáng": gruvboxLight,
    "Gruvbox tối": { ...gruvboxLight, ...variables(".theme-gruvbox.dark {") },
  };
  // [chữ, nền, mức tối thiểu]: chữ chính 7:1, chữ phụ và chữ trên nút 4,5:1.
  const REQUIRED: [string, string, number][] = [
    ["--studio-ink", "--studio-paper", 7],
    ["--studio-ink", "--studio-paper-raised", 7],
    ["--studio-ink-muted", "--studio-paper", 4.5],
    ["--studio-ink-muted", "--studio-paper-sunken", 4.5],
    ["--primary-foreground", "--primary", 4.5],
    ["--studio-on-accent", "--studio-destructive-fill", 4.5],
    ["--studio-on-dark", "--studio-viewport", 7],
    ["--studio-on-dark", "--studio-viewport-deep", 7],
  ];
  for (const [name, values] of Object.entries(variants)) {
    it(name, () => {
      for (const [text, background, minimum] of REQUIRED) {
        expect(contrast(values[text], values[background]), `${text} trên ${background}`).toBeGreaterThanOrEqual(minimum);
      }
    });
  }

  it("Gruvbox định nghĩa đủ mọi biến màu mà bảng mặc định có", () => {
    const names = (selector: string) => {
      const start = CSS.indexOf(selector);
      return [...CSS.slice(start, CSS.indexOf("}", start)).matchAll(/(--[a-z0-9-]+):/g)].map((match) => match[1]).filter((name) => name !== "--radius");
    };
    const base = new Set(names(":root,\n.landing-page {"));
    const light = new Set(names(".theme-gruvbox,\n.theme-gruvbox .landing-page {"));
    expect([...base].filter((name) => !light.has(name))).toEqual([]);
    const darkBase = names(".dark {\n  --studio-paper");
    const dark = new Set(names(".theme-gruvbox.dark {"));
    expect(darkBase.filter((name) => !dark.has(name))).toEqual([]);
  });
});

describe("UI không viết cứng mã màu", () => {
  const files: string[] = [];
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory)) {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(tsx|ts|css)$/.test(entry)) files.push(path);
    }
  };
  walk(join(process.cwd(), "src"));

  it("mọi màu đi qua biến của bảng màu", () => {
    const offenders: string[] = [];
    for (const file of files) {
      const relative = file.slice(process.cwd().length + 1);
      // Nơi định nghĩa bảng màu, ô màu mẫu của menu, và mặt nạ mờ (#000 là alpha của mask, không phải màu vẽ).
      if (relative === "src/app/globals.css" || relative === "src/features/shell/PaletteMenu.tsx" || relative === "src/styles/shadcn-variants.css") continue;
      readFileSync(file, "utf8").split("\n").forEach((line, index) => {
        if (line.includes("themeColor(")) return; // giá trị dự phòng khi chưa có document
        if (/^\s*(\/\/|\*|\/\*)/.test(line)) return; // chú thích
        if (/#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![0-9a-zA-Z_-])|rgba?\(\s*\d/.test(line) || /\b(text|bg|border)-(white|black)\b/.test(line)) {
          offenders.push(`${relative}:${index + 1}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });
});
