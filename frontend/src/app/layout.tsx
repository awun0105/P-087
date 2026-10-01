import type { Metadata } from "next";
import { IBM_Plex_Mono, Plus_Jakarta_Sans } from "next/font/google";

import "./globals.css";

/*
 * Bộ chữ của landing dùng cho toàn bộ giao diện (owner quyết 01/10/2026, PRODUCT.md D-13): Plus Jakarta Sans cho chữ
 * giao diện, IBM Plex Mono cho nhãn kỹ thuật và giá trị (ID, revision, checksum, toạ độ). Cả hai có subset tiếng Việt.
 * Mono chỉ dùng cho chữ phụ nên không preload: trang không phải chờ 6 file font (3 độ đậm × 2 subset) trước khi vẽ.
 */
const sans = Plus_Jakarta_Sans({ subsets: ["latin", "vietnamese"], variable: "--font-jakarta", display: "swap" });
const mono = IBM_Plex_Mono({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
  preload: false,
});

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
    <html lang="vi" className={`${sans.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
