import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "@/features/shell/ThemeToggle";
import { THEME_INIT_SCRIPT, THEME_STORAGE_KEY } from "@/lib/theme";

afterEach(() => {
  cleanup();
  document.documentElement.classList.remove("dark");
  window.localStorage.clear();
});

describe("ThemeToggle", () => {
  it("mặc định là theme sáng và bấm thì chuyển sang tối, lưu lựa chọn", () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Chuyển sang giao diện tối" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "Chuyển sang giao diện sáng" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("hai nút trên cùng trang luôn khớp trạng thái", () => {
    render(<><ThemeToggle /><ThemeToggle /></>);
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(screen.getAllByRole("button", { name: "Chuyển sang giao diện sáng" })).toHaveLength(2);
  });

  it("script khởi tạo chỉ bật theme tối khi đã lưu lựa chọn tối", () => {
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
