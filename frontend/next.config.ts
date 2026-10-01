import type { NextConfig } from "next";

/**
 * Browser gọi API qua chính origin của Next (`/api/v1/...`) và dev server
 * proxy sang FastAPI. Nhờ vậy không cần nới CORS ở backend, và `src/config.py`
 * (ngoài ownership của EX-PRODUCT) không phải sửa.
 *
 * Đặt `REAL2SIM_API_URL` khi backend chạy ở host/port khác.
 */
const BACKEND_ORIGIN = process.env.REAL2SIM_API_URL ?? "http://127.0.0.1:8000";
/** Trang chính của app; giữ khớp với `APP_HOME` trong `src/lib/routes.ts` (config không import được alias `@/`). */
const APP_HOME = "/overview";

const nextConfig: NextConfig = {
  // Không để `next dev` sinh AGENTS.md/CLAUDE.md trong frontend/: harness của repo
  // nằm ở AGENTS.md gốc, file sinh tự động sẽ mâu thuẫn với authority map.
  agentRules: false,
  /**
   * UI cũ (route group `(legacy)`) giữ nguyên code nhưng ẩn khỏi MVP: mọi route cũ
   * chuyển về trang chính của app (Tổng quan, `/overview` — `/` là landing), trừ khi chạy với
   * `LEGACY_UI=1` (`/jobs` trống là trang Jobs mới, chỉ `/jobs/<id>/...` là legacy). Dùng
   * `redirects` thay vì `proxy.ts` vì proxy buộc Next buffer body (mặc định 10MB) → hỏng upload video.
   */
  async redirects() {
    const merged = [
      // Trang "Kịch bản demo" đã gộp vào Scene mới (phần video mẫu).
      { source: "/demo", destination: "/new", permanent: false },
      { source: "/demo/:path*", destination: "/new", permanent: false },
      // Landing từng ở `/landing`; nay là trang đầu `/` (owner quyết 01/10/2026). Giữ link cũ còn dùng được.
      { source: "/landing", destination: "/", permanent: false },
    ];
    if (process.env.LEGACY_UI === "1") return merged;
    return [...merged, ...["/legacy/:path*", "/projects/:path*", "/jobs/:path+", "/viewer/:path*", "/legacy", "/projects", "/viewer"].map(
      (source) => ({ source, destination: APP_HOME, permanent: false }),
    )];
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${BACKEND_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
