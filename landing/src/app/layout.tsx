import type { Metadata } from "next";
import { IBM_Plex_Mono, Plus_Jakarta_Sans } from "next/font/google";

import "./globals.css";
import "@/features/landing/landing.css";

const sans = Plus_Jakarta_Sans({
  subsets: ["latin", "vietnamese"],
  variable: "--font-jakarta",
  display: "swap",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: "Real2Sim Studio — Từ Hiện Thực Đến Mô Phỏng",
  description:
    "Khám phá quy trình Real2Sim: tái tạo video và LiDAR thành scene 3D sẵn sàng mô phỏng cho Isaac Sim, có người kiểm duyệt từng bước.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" className={`${sans.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full bg-[var(--studio-paper)] text-[var(--studio-ink)]">
        {children}
      </body>
    </html>
  );
}
