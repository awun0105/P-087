import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FeedbackHost, notifySuccess } from "@/components/studio/feedback";
import { useSessionDraft, clearStudioDrafts } from "@/features/studio/drafts";
import { EMPTY_SETUP, parseSetupDraft } from "@/features/studio/setup-draft";
import { useUrlState } from "@/features/studio/useUrlState";
import { pageSlice } from "@/features/studio/ListControls";
import { errorMessage } from "@/lib/ui-error";
import { ApiError } from "@/lib/api/client";
import { logout } from "@/lib/api/auth";

beforeEach(() => { sessionStorage.clear(); history.replaceState({ __NA: true }, "", "/"); });
describe("feedback và boundary lỗi", () => {
  it("toast dùng acknowledgement, cùng key không nhân bản và đóng được", async () => {
    render(<FeedbackHost />);
    act(() => { notifySuccess("Đã tạo job.", "create"); notifySuccess("Đã tạo job.", "create"); });
    expect(await screen.findAllByText("Đã tạo job.")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Đóng thông báo" }));
    await waitFor(() => expect(screen.queryByText("Đã tạo job.")).toBeNull());
  });
  it("không hiện transport JSON/trace/path; phân biệt quyền và conflict", () => {
    expect(errorMessage(new ApiError(500, "Traceback /home/user/private/key"))).not.toContain("/home/");
    expect(errorMessage(new ApiError(422, '[{"loc":["body","password"],"input":"secret"}]'))).not.toContain("secret");
    expect(errorMessage(new ApiError(401, "raw"))).toContain("Đăng nhập");
    expect(errorMessage(new ApiError(409, "raw"))).toContain("Tải lại");
    expect(errorMessage(new Error("Mất kết nối"))).toBe("Mất kết nối");
  });
  it("logout HTTP thất bại không resolve như thành công", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 500 }));
    await expect(logout()).rejects.toBeInstanceOf(ApiError);
    fetch.mockRestore();
  });
});
describe("draft trong phiên tab", () => {
  it("khôi phục field allow-list; cô lập actor và xoá chỉ draft của Studio", async () => {
    sessionStorage.setItem("studio:draft:video:A", JSON.stringify({ ...EMPTY_SETUP, name: "Kho A", password: "do-not-restore" }));
    const draft = renderHook(({ actor }) => useSessionDraft("video:" + actor, EMPTY_SETUP, parseSetupDraft), { initialProps: { actor: "A" } });
    await waitFor(() => expect(draft.result.current.ready).toBe(true));
    expect(draft.result.current.value.name).toBe("Kho A");
    expect(draft.result.current.value).not.toHaveProperty("password");
    draft.rerender({ actor: "B" });
    await waitFor(() => expect(draft.result.current.ready).toBe(true));
    expect(draft.result.current.value.name).toBe("");
    expect(JSON.parse(sessionStorage.getItem("studio:draft:video:B")!).name).toBe("");
    sessionStorage.setItem("other-app", "keep");
    clearStudioDrafts();
    expect(sessionStorage.getItem("other-app")).toBe("keep");
    expect(sessionStorage.getItem("studio:draft:video:A")).toBeNull();
  });
  it("storage bị chặn vẫn nhập được trong bộ nhớ", async () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const draft = renderHook(() => useSessionDraft("video", EMPTY_SETUP, parseSetupDraft));
    await waitFor(() => expect(draft.result.current.ready).toBe(true));
    act(() => draft.result.current.setValue((old) => ({ ...old, name: "Trong bộ nhớ" })));
    expect(draft.result.current.value.name).toBe("Trong bộ nhớ");
    get.mockRestore(); set.mockRestore();
  });
  it("không nhận consent sai kiểu từ storage", () => {
    expect(parseSetupDraft({ ...EMPTY_SETUP, rights: "true" })).toBeNull();
  });
});
describe("URL và phân trang", () => {
  it("đổi tab giữ query khác và metadata history; popstate khôi phục vùng", () => {
    const hook = renderHook(() => useUrlState());
    act(() => hook.result.current.update({ tab: "studio", mode: "gaussian" }));
    expect(hook.result.current.params.get("mode")).toBe("gaussian");
    act(() => hook.result.current.update({ tab: "progress" }));
    expect(hook.result.current.params.get("mode")).toBe("gaussian");
    act(() => { history.replaceState(history.state, "", "/?tab=results"); window.dispatchEvent(new PopStateEvent("popstate", { state: history.state })); });
    expect(hook.result.current.params.get("tab")).toBe("results");
  });
  it("clamp trang sai, chia 12/20 mục, không làm mất trang cuối", () => {
    const rows = Array.from({ length: 25 }, (_, i) => i);
    expect(pageSlice(rows, "-4", 12).page).toBe(1);
    expect(pageSlice(rows, "999", 12)).toMatchObject({ page: 3, totalPages: 3, items: [24] });
    expect(pageSlice(rows, "2", 20).items).toEqual([20, 21, 22, 23, 24]);
  });
});
