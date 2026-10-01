/** Landing là trang đầu `/`; CTA vào app phải qua đăng nhập; route cũ không rơi về landing. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";
import { LandingPage } from "@/features/landing/LandingPage";
import { APP_HOME, LANDING, STUDIO_ENTRY } from "@/lib/routes";

describe("landing → app", () => {
  it("mọi CTA Open Studio dẫn tới màn đăng nhập với đích là Tổng quan", () => {
    render(<LandingPage />);
    const entries = screen.getAllByRole("link", { name: /Open (Real2Sim )?Studio/ });
    expect(entries).toHaveLength(3);
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
