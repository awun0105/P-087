import type { Metadata } from "next";
import { LandingPage } from "@/features/landing/LandingPage";
import "@/features/landing/landing.css";

export const metadata: Metadata = {
  title: "Real2Sim Studio — Từ Hiện Thực Đến Mô Phỏng",
  description: "Khám phá quy trình Real2Sim: tái tạo video và LiDAR thành scene 3D sẵn sàng mô phỏng cho Isaac Sim, có người kiểm duyệt từng bước.",
};

/**
 * Trang đầu tiên khi mở domain (owner quyết 01/10/2026): landing nằm ngoài AppShell; app Tổng quan ở `/overview` và
 * các CTA của landing dẫn vào app qua đăng nhập (`STUDIO_ENTRY` trong `lib/routes.ts`).
 */
export default function LandingRoute() {
  return <div lang="vi"><LandingPage /></div>;
}
