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
  typescript: { tsconfigPath: "tsconfig.build.json" },
  // `localhost` đã được Next cho phép mặc định; `127.0.0.1` thì không, nên dev server trả 403 cho HMR và
  // trang đăng nhập mở qua `127.0.0.1` treo ở "Đang kiểm tra phiên đăng nhập…" (chỉ ảnh hưởng `next dev`).
  allowedDevOrigins: ["127.0.0.1"],
  // Không để `next dev` sinh AGENTS.md/CLAUDE.md trong frontend/: harness của repo
  // nằm ở AGENTS.md gốc, file sinh tự động sẽ mâu thuẫn với authority map.
  agentRules: false,
  async headers() {
    return [{
      source: "/demo-workspace/:path*",
      headers: [
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "Cache-Control", value: "no-store" },
      ],
    }];
  },
  /**
   * UI cũ (trang project/job/viewer P0) đã xoá ngày 02/10/2026 sau khi phần validation/duyệt/phát hành có trong Studio
   * (STUDIO_UX_SPEC.md D-10). Vẫn chuyển hướng các URL cũ về trang chính của app để link đã lưu không rơi vào 404
   * (`/jobs` trống là trang Jobs của Studio, chỉ `/jobs/<id>/...` là URL cũ). Dùng `redirects` thay vì `proxy.ts` vì
   * proxy buộc Next buffer body (mặc định 10MB) → hỏng upload video.
   */
  async redirects() {
    return [
      // Trang "Kịch bản demo" đã gộp vào Scene mới (phần video mẫu).
      { source: "/demo", destination: "/new/try-demo", permanent: false },
      { source: "/demo/:path*", destination: "/new/try-demo", permanent: false },
      // Landing từng ở `/landing`; nay là trang đầu `/` (owner quyết 01/10/2026). Giữ link cũ còn dùng được.
      { source: "/landing", destination: "/", permanent: false },
      // Trang Jobs đã gộp vào Scenes (chế độ Bảng) theo quyết định UX 04/10/2026.
      { source: "/jobs", destination: "/scenes", permanent: false },
      ...["/legacy/:path*", "/projects/:path*", "/jobs/:path+", "/viewer/:path*", "/legacy", "/projects", "/viewer"].map(
        (source) => ({ source, destination: APP_HOME, permanent: false }),
      ),
    ];
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
