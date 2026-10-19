import type { Metadata } from "next";
import { IBM_Plex_Mono, Plus_Jakarta_Sans } from "next/font/google";

import { LANG_INIT_SCRIPT } from "@/lib/i18n";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

/*
 * Bộ chữ của landing dùng cho toàn bộ giao diện (owner quyết 01/10/2026, STUDIO_UX_SPEC.md D-13): Plus Jakarta Sans cho chữ
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
  title: "Real2Sim Studio — Từ video thật đến scene mô phỏng",
  description:
    "Biến video quay môi trường thật thành scene 3D đúng tỉ lệ mét, tách được vật thể, có collider và xuất OpenUSD. Lát cắt đầu tiên: nhà kho trong nhà và NVIDIA Isaac Sim.",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "any" },
    ],
  },
};

/**
 * Root layout chỉ giữ html/body, font và script theme; khung giao diện của app nằm ở route group `(studio)`, còn
 * landing (`/`) tự dựng khung riêng.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Script theme gắn class `dark` lên <html> trước khi React hydrate nên phải bỏ cảnh báo lệch thuộc tính ở thẻ này.
    <html lang="vi" className={`${sans.variable} ${mono.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT + LANG_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
