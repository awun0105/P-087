/** Route stream upload phải mang cookie phiên sang FastAPI (bật đăng nhập thì thiếu cookie → 401). */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "@/app/api/v1/uploads/route";

describe("/api/v1/uploads route handler", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn(async () => new Response("{}", { status: 200 }));
  });

  it("GET chuyển tiếp cookie phiên", async () => {
    await GET(new Request("http://web/api/v1/uploads", { headers: { cookie: "r2s_session=abc" } }));
    const [, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(new Headers(init?.headers).get("cookie")).toBe("r2s_session=abc");
  });

  it("POST chuyển tiếp cookie và Content-Type, giữ query filename", async () => {
    await POST(
      new Request("http://web/api/v1/uploads?filename=a.mp4", {
        method: "POST",
        body: "x",
        headers: { cookie: "r2s_session=abc", "Content-Type": "video/mp4" },
      }),
    );
    const [url, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(String(url)).toContain("/api/v1/uploads?filename=a.mp4");
    const headers = new Headers(init?.headers);
    expect(headers.get("cookie")).toBe("r2s_session=abc");
    expect(headers.get("content-type")).toBe("video/mp4");
  });
});
