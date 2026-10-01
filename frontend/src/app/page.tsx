import type { Metadata } from "next";
import { LandingPage } from "@/features/landing/LandingPage";
import "@/features/landing/landing.css";

export const metadata: Metadata = {
  title: "Real2Sim Studio — From Reality to Simulation",
  description: "Explore the Real2Sim workflow, then open Studio to work with your scenes.",
};

/**
 * Trang đầu tiên khi mở domain (owner quyết 01/10/2026): landing nằm ngoài AppShell; app Tổng quan ở `/overview` và
 * các CTA của landing dẫn vào app qua đăng nhập (`STUDIO_ENTRY` trong `lib/routes.ts`).
 */
export default function LandingRoute() {
  return <div lang="en"><LandingPage /></div>;
}
