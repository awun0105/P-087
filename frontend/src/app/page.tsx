import type { Metadata } from "next";
import { IBM_Plex_Mono, Plus_Jakarta_Sans } from "next/font/google";

import { LandingPage } from "@/features/landing/LandingPage";
import "@/features/landing/landing.css";

const sans = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-landing-sans", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-landing-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Real2Sim Studio — From Reality to Simulation",
  description: "Explore the Real2Sim workflow, then open Studio to work with your scenes.",
};

/**
 * Trang đầu tiên khi mở domain (owner quyết 01/10/2026): landing nằm ngoài AppShell; app Tổng quan ở `/overview` và
 * các CTA của landing dẫn vào app qua đăng nhập (`STUDIO_ENTRY` trong `lib/routes.ts`).
 */
export default function LandingRoute() {
  return <div lang="en" className={`${sans.variable} ${mono.variable}`}><LandingPage /></div>;
}
