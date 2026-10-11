import { describe, expect, it } from "vitest";

import { safeNext } from "@/features/studio/auth/AuthForms";
import { canDecideReview, canEdit, isReviewer, type Me } from "@/lib/api/auth";

const user = (role: "editor" | "reviewer"): Me["user"] => ({
  user_id: "user-1",
  email: "a@example.com",
  display_name: "A",
  role,
  active: true,
  daily_job_quota: 10,
});

describe("quyền phía UI (chỉ để ẩn/hiện; backend vẫn kiểm)", () => {
  it("tắt đăng nhập thì ai cũng thao tác được", () => {
    const me: Me = { auth_required: false, user: null };
    expect(canEdit(me)).toBe(true);
    expect(isReviewer(me)).toBe(true);
  });

  it("bật đăng nhập: khách chỉ xem mẫu, Editor sửa, Reviewer thêm quyền duyệt", () => {
    expect(canEdit({ auth_required: true, user: null })).toBe(false);
    expect(canEdit({ auth_required: true, user: user("editor") })).toBe(true);
    expect(isReviewer({ auth_required: true, user: user("editor") })).toBe(false);
    expect(isReviewer({ auth_required: true, user: user("reviewer") })).toBe(true);
    expect(canEdit(null)).toBe(false);
  });
});

describe("safeNext", () => {
  it("chỉ cho quay lại đường dẫn nội bộ", () => {
    expect(safeNext("/new?sample=a")).toBe("/new?sample=a");
    // Đích mặc định là Tổng quan của app; `/` là landing nên không phải nơi quay về sau khi đăng nhập.
    expect(safeNext("https://evil.example")).toBe("/overview");
    expect(safeNext("//evil.example")).toBe("/overview");
    expect(safeNext(null)).toBe("/overview");
  });

  it("duyệt/phát hành luôn cần phiên Reviewer, kể cả khi tắt đăng nhập", () => {
    expect(canDecideReview({ auth_required: false, user: null })).toBe(false);
    expect(canDecideReview({ auth_required: true, user: null })).toBe(false);
    expect(canDecideReview({ auth_required: true, user: user("editor") })).toBe(false);
    expect(canDecideReview({ auth_required: true, user: user("reviewer") })).toBe(true);
    expect(canDecideReview(null)).toBe(false);
  });
});
