import { redirect } from "next/navigation";

import { STUDIO_ENTRY } from "@/lib/routes";

/**
 * Trang đầu của WebApp: Landing page đã được tách riêng và host độc lập tại c4-app-087.pages.dev.
 * Khi truy cập vào WebApp chính, chuyển hướng trực tiếp tới màn đăng nhập (hoặc Tổng quan nếu đã đăng nhập).
 */
export default function RootRoute() {
  redirect(STUDIO_ENTRY);
}
