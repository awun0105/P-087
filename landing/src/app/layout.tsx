import type { Metadata } from "next";
import { IBM_Plex_Mono, Plus_Jakarta_Sans } from "next/font/google";

import { LANG_INIT_SCRIPT } from "@/lib/i18n";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" className={`${sans.variable} ${mono.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT + LANG_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full bg-[var(--studio-paper)] text-[var(--studio-ink)]">
        {children}
      </body>
    </html>
  );
}
