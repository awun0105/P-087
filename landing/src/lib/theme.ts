export type Theme = "light" | "dark";
export type Palette = "gruvbox" | "classic";

export const THEME_STORAGE_KEY = "r2s-theme";
export const PALETTE_STORAGE_KEY = "r2s-palette";
// Gruvbox là bảng màu mặc định (token ở :root/.dark); "classic" là bảng be + cam cũ, bật bằng class.
const CLASSIC_CLASS = "theme-classic";
const EVENT = "r2s:theme";

/** Chạy trong <head> trước khi vẽ. Landing mặc định tối; chỉ sáng khi người dùng đã chọn sáng. Lỗi đọc storage thì tối. */
export const THEME_INIT_SCRIPT = `try{var c=document.documentElement.classList;if(localStorage.getItem("${THEME_STORAGE_KEY}")!=="light")c.add("dark");var p=localStorage.getItem("${PALETTE_STORAGE_KEY}");if(p==="classic"||p==="default")c.add("${CLASSIC_CLASS}")}catch(e){}`;

export function currentTheme(): Theme {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function currentPalette(): Palette {
  return typeof document !== "undefined" && document.documentElement.classList.contains(CLASSIC_CLASS) ? "classic" : "gruvbox";
}

function store(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {}
  window.dispatchEvent(new Event(EVENT));
}

export function applyTheme(theme: Theme): void {
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }
  store(THEME_STORAGE_KEY, theme);
}

export function applyPalette(palette: Palette): void {
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle(CLASSIC_CLASS, palette === "classic");
  }
  store(PALETTE_STORAGE_KEY, palette);
}

export function subscribeTheme(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}

export function themeKey(): string {
  return `${currentTheme()}:${currentPalette()}`;
}
