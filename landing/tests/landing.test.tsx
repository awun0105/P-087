/** Landing là trang đầu `/`: CTA vào app phải qua đăng nhập, mục trong trang không làm hỏng nút Back. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, onTestFinished } from "vitest";

import { CONTENT_EN, CONTENT_VI } from "@/features/landing/content";
import { LandingPage } from "@/features/landing/LandingPage";

const STUDIO_ENTRY = "/login?next=%2Foverview";

describe("landing → app", () => {
  it("mọi CTA Đăng nhập Studio dẫn tới màn đăng nhập với đích là Tổng quan", () => {
    render(<LandingPage />);
    const entries = screen.getAllByRole("link", { name: "Đăng nhập Studio" });
    expect(entries).toHaveLength(2);
    for (const link of entries) expect(link).toHaveAttribute("href", STUDIO_ENTRY);
    expect(screen.getAllByRole("link").filter((link) => link.getAttribute("href") === "/")).toHaveLength(0);
  });

  it("nút Truy cập Studio trong header dẫn tới màn đăng nhập Studio", () => {
    render(<LandingPage />);
    const studioLinks = screen.getAllByRole("link", { name: "Truy cập Studio" });
    expect(studioLinks.length).toBeGreaterThanOrEqual(1);
    expect(studioLinks[0]).toHaveAttribute("href", STUDIO_ENTRY);
  });
});

describe("cấu trúc trang", () => {
  it("header và footer nằm ngoài <main> để giữ vai trò banner/contentinfo", () => {
    render(<LandingPage />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("section Scene mẫu ẩn khi API không trả scene nào", () => {
    const { container } = render(<LandingPage />);
    expect(container.querySelector("#samples")).toBeNull();
  });

  it("mỗi mục menu trỏ tới một section có thật", () => {
    const { container } = render(<LandingPage />);
    for (const { href } of CONTENT_VI.NAV) {
      expect(container.querySelector(href), href).not.toBeNull();
    }
  });

  it("chỉ còn các section đã gộp: bối cảnh, vai bị kể lại và ba lớp không quay lại", () => {
    const { container } = render(<LandingPage />);
    for (const id of ["context", "solution", "roadmap"]) {
      expect(container.querySelector(`#${id}`), id).toBeNull();
    }
  });

  it("bản Việt và bản Anh có cùng cấu trúc, không bên nào thiếu mục", () => {
    const shape = (v: unknown): unknown =>
      Array.isArray(v) ? [v.length, v.map(shape)]
      : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, shape(x)]))
      : typeof v;
    expect(shape(CONTENT_EN)).toEqual(shape(CONTENT_VI));
  });

  it("không câu nào trong nội dung tiếng Việt xuất hiện hai lần", () => {
    const seen = new Map<string, number>();
    const walk = (v: unknown) => {
      if (typeof v === "string") {
        if (v.length > 40) seen.set(v, (seen.get(v) ?? 0) + 1);
      } else if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === "object") Object.values(v).forEach(walk);
    };
    walk(CONTENT_VI);
    expect([...seen].filter(([, n]) => n > 1).map(([s]) => s)).toEqual([]);
  });
});

describe("mục trong landing không làm hỏng nút Back", () => {
  it("bấm link #mục: cuộn tới mục, đổi hash bằng replaceState (giữ state của router), không thêm history entry", () => {
    history.replaceState({ __NA: true, tree: "landing" }, "", "/");
    const before = history.length;
    const scrolled: string[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoView() { scrolled.push(this.id); };
    onTestFinished(() => { Element.prototype.scrollIntoView = original; });
    render(<LandingPage />);

    fireEvent.click(screen.getAllByRole("link", { name: "Quy trình" })[0]);

    expect(scrolled).toEqual(["workflow"]);
    expect(location.hash).toBe("#workflow");
    expect(history.length).toBe(before);
    expect(history.state).toMatchObject({ __NA: true, tree: "landing" });
    expect(document.activeElement?.id).toBe("workflow");
  });

  it("click có phím bổ trợ để nguyên cho trình duyệt (mở tab mới)", () => {
    history.replaceState({ __NA: true }, "", "/");
    render(<LandingPage />);
    const link = screen.getAllByRole("link", { name: "Bài toán" })[0];
    const event = new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true });
    fireEvent(link, event);
    expect(event.defaultPrevented).toBe(false);
  });
});

describe("header: theme, i18n", () => {
  it("nút đổi theme chuyển đổi qua lại giữa sáng và tối", () => {
    render(<LandingPage />);
    fireEvent.click(screen.getByRole("button", { name: "Chuyển sang giao diện tối" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Chuyển sang giao diện sáng" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("nút đổi ngôn ngữ chuyển đổi qua lại giữa Tiếng Việt và Tiếng Anh", () => {
    render(<LandingPage />);
    expect(document.documentElement.getAttribute("lang")).toBe("vi");

    fireEvent.click(screen.getByRole("button", { name: "Chuyển sang tiếng Anh (EN)" }));
    expect(document.documentElement.getAttribute("lang")).toBe("en");
    expect(screen.getAllByRole("link", { name: "Workflow" })[0]).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Switch to Vietnamese (VI)" }));
    expect(document.documentElement.getAttribute("lang")).toBe("vi");
    expect(screen.getAllByRole("link", { name: "Quy trình" })[0]).toBeInTheDocument();
  });
});
