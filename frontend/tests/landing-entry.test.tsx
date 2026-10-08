/** Landing là trang đầu `/`; CTA vào app phải qua đăng nhập; route cũ không rơi về landing. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";
import { LandingPage } from "@/features/landing/LandingPage";
import { APP_HOME, LANDING, STUDIO_ENTRY } from "@/lib/routes";

describe("landing → app", () => {
  it("mọi CTA Đăng nhập Studio dẫn tới màn đăng nhập với đích là Tổng quan", () => {
    render(<LandingPage />);
    const entries = screen.getAllByRole("link", { name: "Đăng nhập Studio" });
    expect(entries).toHaveLength(2);
    for (const link of entries) expect(link).toHaveAttribute("href", "/login?next=%2Foverview");
    expect(STUDIO_ENTRY).toBe("/login?next=%2Foverview");
    // Không còn link nào coi `/` là app: trên landing `/` chính là trang đang xem.
    expect(screen.getAllByRole("link").filter((link) => link.getAttribute("href") === "/")).toHaveLength(0);
  });

  it("redirect: /landing cũ về trang đầu, route legacy về Tổng quan (không về landing)", async () => {
    const redirects = await nextConfig.redirects!();
    const target = (source: string) => redirects.find((item) => item.source === source)?.destination;
    expect(LANDING).toBe("/");
    expect(target("/landing")).toBe(LANDING);
    expect(target("/projects")).toBe(APP_HOME);
    expect(target("/jobs/:path+")).toBe(APP_HOME);
    expect(redirects.some((item) => item.source !== "/landing" && item.destination === "/")).toBe(false);
  });
});

describe("mục trong landing không làm hỏng nút Back", () => {
  it("bấm link #mục: cuộn tới mục, đổi hash bằng replaceState (giữ state của router), không thêm history entry", async () => {
    const { fireEvent } = await import("@testing-library/react");
    history.replaceState({ __NA: true, tree: "landing" }, "", "/");
    const before = history.length;
    const scrolled: string[] = [];
    Element.prototype.scrollIntoView = function scrollIntoView() { scrolled.push(this.id); };
    render(<LandingPage />);

    fireEvent.click(screen.getAllByRole("link", { name: "Quy trình" })[0]);

    expect(scrolled).toEqual(["workflow"]);
    expect(location.hash).toBe("#workflow");
    expect(history.length).toBe(before);
    // State của Next vẫn còn trên entry này → `popstate` khi Back từ app được router xử lý, landing hiện lại.
    expect(history.state).toMatchObject({ __NA: true, tree: "landing" });
    expect(document.activeElement?.id).toBe("workflow");
  });

  it("click có phím bổ trợ để nguyên cho trình duyệt (mở tab mới)", async () => {
    const { fireEvent } = await import("@testing-library/react");
    history.replaceState({ __NA: true }, "", "/");
    render(<LandingPage />);
    const link = screen.getAllByRole("link", { name: "Bài toán" })[0];
    const event = new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true });
    fireEvent(link, event);
    expect(event.defaultPrevented).toBe(false);
  });
});

describe("header: studio, theme, i18n controls", () => {
  it("nút Truy cập Studio trong header dẫn tới màn đăng nhập Studio", () => {
    render(<LandingPage />);
    const studioLinks = screen.getAllByRole("link", { name: "Truy cập Studio" });
    expect(studioLinks.length).toBeGreaterThanOrEqual(1);
    expect(studioLinks[0]).toHaveAttribute("href", STUDIO_ENTRY);
  });

  it("nút đổi theme chuyển đổi qua lại giữa sáng và tối", async () => {
    const { fireEvent } = await import("@testing-library/react");
    render(<LandingPage />);
    const themeBtn = screen.getByRole("button", { name: "Chuyển sang giao diện tối" });
    fireEvent.click(themeBtn);
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    const themeBtnLight = screen.getByRole("button", { name: "Chuyển sang giao diện sáng" });
    fireEvent.click(themeBtnLight);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("nút đổi ngôn ngữ chuyển đổi qua lại giữa Tiếng Việt và Tiếng Anh", async () => {
    const { fireEvent } = await import("@testing-library/react");
    render(<LandingPage />);
    expect(document.documentElement.getAttribute("lang")).toBe("vi");

    const langBtn = screen.getByRole("button", { name: "Chuyển sang tiếng Anh (EN)" });
    fireEvent.click(langBtn);
    expect(document.documentElement.getAttribute("lang")).toBe("en");
    expect(screen.getAllByRole("link", { name: "Workflow" })[0]).toBeInTheDocument();

    const langBtnVi = screen.getByRole("button", { name: "Switch to Vietnamese (VI)" });
    fireEvent.click(langBtnVi);
    expect(document.documentElement.getAttribute("lang")).toBe("vi");
    expect(screen.getAllByRole("link", { name: "Quy trình" })[0]).toBeInTheDocument();
  });
});

