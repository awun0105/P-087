import type { Metadata } from "next";
import { Inter } from "next/font/google";

import "./globals.css";

const inter = Inter({ subsets: ["latin", "vietnamese"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Real2Sim Studio",
  description: "Dựng scene 3D Gaussian Splatting từ video để chỉnh sửa và đưa vào mô phỏng.",
};

/**
 * Root layout chỉ giữ html/body và font; khung giao diện thuộc từng route group:
 * `(studio)` là Studio MVP, `(legacy)` là UI cũ được ẩn sau flag `LEGACY_UI`.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
