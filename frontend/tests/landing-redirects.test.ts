/** Landing chạy ở app riêng (`landing/`); app này chỉ giữ redirect: /landing cũ về trang đầu, route legacy về Tổng quan. */
import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";
import { APP_HOME, LANDING, STUDIO_ENTRY } from "@/lib/routes";

describe("redirect về landing và app", () => {
  it("lối vào Studio là màn đăng nhập với đích là Tổng quan", () => {
    expect(STUDIO_ENTRY).toBe("/login?next=%2Foverview");
  });

  it("/landing cũ về trang đầu, route legacy về Tổng quan (không về landing)", async () => {
    const redirects = await nextConfig.redirects!();
    const target = (source: string) => redirects.find((item) => item.source === source)?.destination;
    expect(LANDING).toBe("/");
    expect(target("/landing")).toBe(LANDING);
    expect(target("/projects")).toBe(APP_HOME);
    expect(target("/jobs/:path+")).toBe(APP_HOME);
    expect(redirects.some((item) => item.source !== "/landing" && item.destination === "/")).toBe(false);
  });
});
