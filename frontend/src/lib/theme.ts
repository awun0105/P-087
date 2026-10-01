/**
 * Theme sáng/tối của Studio (STUDIO_UX_SPEC.md D-14). Lựa chọn là sở thích hiển thị của từng trình duyệt nên nằm ở
 * localStorage, không phải state của backend. Class `dark` trên <html> là nguồn duy nhất cho CSS; script
 * `THEME_INIT_SCRIPT` gắn class trước lần vẽ đầu để trang không nháy theme sáng.
 */
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "r2s-theme";
const EVENT = "r2s:theme";

/** Chạy trong <head> trước khi vẽ; lỗi đọc storage (chế độ riêng tư, bị chặn) thì giữ theme sáng mặc định. */
export const THEME_INIT_SCRIPT = `try{if(localStorage.getItem("${THEME_STORAGE_KEY}")==="dark")document.documentElement.classList.add("dark")}catch(e){}`;

export function currentTheme(): Theme {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Không lưu được thì theme vẫn đổi cho phiên này.
  }
  window.dispatchEvent(new Event(EVENT));
}

export function subscribeTheme(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
