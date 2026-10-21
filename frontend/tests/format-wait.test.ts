import { describe, expect, it } from "vitest";

import { formatUpdatedAt, formatWait } from "@/lib/format";

describe("formatWait", () => {
  it("đổi phút dài thành giờ và ngày", () => {
    expect(formatWait(10 * 60)).toBe("10 phút");
    expect(formatWait(185 * 60)).toBe("3 giờ 5 phút");
    expect(formatWait(5248 * 60)).toBe("3 ngày 15 giờ");
  });
});

describe("formatUpdatedAt", () => {
  it("kèm ngày khi mốc không phải hôm nay", () => {
    const at = "2026-10-18T00:44:31Z";
    expect(formatUpdatedAt(at, Date.parse(at) + 60_000)).not.toMatch(/2026/);
    expect(formatUpdatedAt(at, Date.parse(at) + 3 * 86_400_000)).toMatch(/2026/);
  });
});
