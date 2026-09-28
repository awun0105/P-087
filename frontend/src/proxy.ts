import { NextResponse, type NextRequest } from "next/server";

/**
 * Ẩn UI cũ (route group `(legacy)`) khỏi MVP mà không xóa code.
 *
 * Đặt `LEGACY_UI=1` khi chạy Next để mở lại các màn hình project/job/validation/
 * review/release cũ; mặc định mọi route cũ chuyển về Studio.
 */
export function proxy(request: NextRequest): NextResponse {
  if (process.env.LEGACY_UI === "1") return NextResponse.next();
  return NextResponse.redirect(new URL("/", request.url));
}

export const config = {
  matcher: ["/legacy/:path*", "/projects/:path*", "/jobs/:path*", "/viewer/:path*"],
};
