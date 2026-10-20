/**
 * Giao diện của Studio: hai lựa chọn độc lập — chế độ sáng/tối và bảng màu (mặc định
 * be + cam, hoặc Gruvbox). Đây là sở thích hiển thị của từng trình duyệt nên nằm ở localStorage, không phải state của
 * backend. Class trên <html> là nguồn duy nhất cho CSS (`dark`, `theme-gruvbox`); script `THEME_INIT_SCRIPT` gắn class
 * trước lần vẽ đầu để trang không nháy sang giao diện mặc định.
 */
export type Theme = "light" | "dark";
export type Palette = "default" | "gruvbox";

export const THEME_STORAGE_KEY = "r2s-theme";
export const PALETTE_STORAGE_KEY = "r2s-palette";
const GRUVBOX_CLASS = "theme-gruvbox";
const EVENT = "r2s:theme";

/** Chạy trong <head> trước khi vẽ; lỗi đọc storage (chế độ riêng tư, bị chặn) thì giữ giao diện mặc định. */
export const THEME_INIT_SCRIPT = `try{var c=document.documentElement.classList;if(localStorage.getItem("${THEME_STORAGE_KEY}")==="dark")c.add("dark");if(localStorage.getItem("${PALETTE_STORAGE_KEY}")==="gruvbox")c.add("${GRUVBOX_CLASS}")}catch(e){}`;

export function currentTheme(): Theme {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function currentPalette(): Palette {
  return typeof document !== "undefined" && document.documentElement.classList.contains(GRUVBOX_CLASS) ? "gruvbox" : "default";
}

function store(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Không lưu được thì giao diện vẫn đổi cho phiên này.
  }
  window.dispatchEvent(new Event(EVENT));
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  store(THEME_STORAGE_KEY, theme);
}

export function applyPalette(palette: Palette): void {
  document.documentElement.classList.toggle(GRUVBOX_CLASS, palette === "gruvbox");
  store(PALETTE_STORAGE_KEY, palette);
}

/** Báo khi chế độ sáng/tối hoặc bảng màu đổi (cùng một sự kiện: thứ gì đọc màu đều phải đọc lại). */
export function subscribeTheme(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}

/**
 * Giá trị hiện tại của một biến màu (vd `--studio-sage`), cho thứ không dùng được CSS: material của lớp phủ 3D.
 * `fallback` dùng khi chưa có document (SSR) hoặc biến chưa được định nghĩa.
 */
export function themeColor(variable: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
  return value || fallback;
}

/** Khoá đổi mỗi khi chế độ hoặc bảng màu đổi; snapshot ổn định cho `useSyncExternalStore`. */
export function themeKey(): string {
  return `${currentTheme()}:${currentPalette()}`;
}
