/**
 * Đường dẫn gốc của ứng dụng (owner quyết 01/10/2026):
 *
 * - `/` là trang giới thiệu (landing), nằm ngoài AppShell — trang đầu tiên khi mở domain;
 * - trang chính của app là Tổng quan ở `/overview`;
 * - từ landing vào app phải đi qua đăng nhập (màn đăng nhập có lối sang đăng ký bằng mã mời).
 */
export const LANDING = "/";
export const APP_HOME = "/overview";

/**
 * Đích của các CTA "Open Studio" trên landing: màn đăng nhập, xong thì vào Tổng quan. Người đã đăng nhập — hoặc
 * deployment không bật đăng nhập (chế độ local) — được màn đăng nhập chuyển thẳng tới đích.
 */
export const STUDIO_ENTRY = `/login?next=${encodeURIComponent(APP_HOME)}`;
