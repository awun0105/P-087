import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/setup.ts"],
    // Three.js/WebGL không dựng được trong jsdom; test chỉ chạy phần logic thuần
    // và các component không cần canvas. Phần render 3D được kiểm bằng browser
    // smoke riêng (PRODUCT-06 §10), không giả lập ở đây.
    globals: false,
  },
});
