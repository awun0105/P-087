import { describe, expect, it } from "vitest";

import { readyPhysicsHint } from "@/features/viewer/usePhysicsPlay";

describe("readyPhysicsHint", () => {
  it("chỉ mời đẩy khi có vật có khối lượng", () => {
    expect(readyPhysicsHint(22, 0)).toBe("22 vật chặn đường, chưa có vật nào đẩy được");
    expect(readyPhysicsHint(22, 3)).toBe("Đi vào vật để đẩy · 3 vật đẩy được");
  });
});
