import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library chỉ tự cleanup khi `globals: true`; ở đây tắt globals nên
// phải gọi tay, nếu không DOM của test trước rò sang test sau.
afterEach(() => {
  cleanup();
  // Trả html và localStorage về mặc định để test theme/ngôn ngữ không phụ thuộc thứ tự chạy.
  document.documentElement.className = "";
  document.documentElement.setAttribute("lang", "vi");
  window.localStorage.clear();
});

if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}
