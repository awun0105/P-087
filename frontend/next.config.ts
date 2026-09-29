import type { NextConfig } from "next";

/**
 * Browser gọi API qua chính origin của Next (`/api/v1/...`) và dev server
 * proxy sang FastAPI. Nhờ vậy không cần nới CORS ở backend, và `src/config.py`
 * (ngoài ownership của EX-PRODUCT) không phải sửa.
 *
 * Đặt `REAL2SIM_API_URL` khi backend chạy ở host/port khác.
 */
const BACKEND_ORIGIN = process.env.REAL2SIM_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Không để `next dev` sinh AGENTS.md/CLAUDE.md trong frontend/: harness của repo
  // nằm ở AGENTS.md gốc, file sinh tự động sẽ mâu thuẫn với authority map.
  agentRules: false,
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
