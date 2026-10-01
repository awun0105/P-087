import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FeedbackHost, notifySuccess } from "@/components/studio/feedback";
import { useSessionDraft, clearStudioDrafts } from "@/features/studio/drafts";
import { EMPTY_SETUP, parseSetupDraft } from "@/features/studio/setup-draft";
import { useUrlState } from "@/features/studio/useUrlState";
import { pageSlice } from "@/features/studio/ListControls";
import { authErrorMessage, errorMessage } from "@/lib/ui-error";
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
  it("giữ lý do backend viết cho người dùng ở 403/409/429; chi tiết kỹ thuật và câu mặc định vẫn bị thay", () => {
    // Phản hồi thật của backend (đo trên API ngày 2026-10-01): 409 không chỉ là "dữ liệu đã đổi".
    const metric = "A–B quá ngắn so với C–D nên không kiểm chắc được; chọn vật dài hơn làm A–B";
    expect(errorMessage(new ApiError(409, metric))).toBe(metric);
    expect(errorMessage(new ApiError(409, "Scene này không có số đo LiDAR; nhập khoảng cách đo ngoài đời"))).toContain("LiDAR");
    expect(errorMessage(new ApiError(403, "Chỉ Reviewer được duyệt và phát hành"))).toBe("Chỉ Reviewer được duyệt và phát hành");
    expect(errorMessage(new ApiError(429, "Thử đăng nhập quá nhiều lần; đợi vài phút"))).toContain("đợi vài phút");
    // Chi tiết kỹ thuật, câu mặc định của framework/proxy, HTML: không hiện, dùng hướng phục hồi theo mã.
    expect(errorMessage(new ApiError(409, "artifact does not exist: artifact://jobs/job-a/scene/x.json"))).toContain("Tải lại");
    expect(errorMessage(new ApiError(409, "checksum mismatch: expected sha256:abc, observed sha256:def"))).toContain("Tải lại");
    expect(errorMessage(new ApiError(403, "Forbidden"))).toContain("chưa có quyền");
    expect(errorMessage(new ApiError(405, "Method Not Allowed"))).toBe("Không thực hiện được thao tác. Hãy thử lại.");
    expect(errorMessage(new ApiError(400, "<html><body>Bad Gateway</body></html>"))).not.toContain("<html");
    expect(errorMessage(new ApiError(503, "Máy chủ đang bảo trì tới 9 giờ"))).toBe("Máy chủ chưa xử lý được yêu cầu. Hãy thử lại.");
    // 401/404 giữ hướng phục hồi chung của STUDIO_UX_SPEC.md, kể cả khi backend có câu riêng.
    expect(errorMessage(new ApiError(401, "Cần đăng nhập"))).toContain("Đăng nhập để tiếp tục");
    expect(errorMessage(new ApiError(404, "không tìm thấy upload: upload-x"))).toContain("quay về Scenes");
  });
  it("thao tác tài khoản: 401 là bị từ chối có lý do, không phải hết phiên", () => {
    expect(authErrorMessage(new ApiError(401, "Sai email hoặc mật khẩu"), "Đăng nhập thất bại")).toBe("Sai email hoặc mật khẩu");
    expect(authErrorMessage(new ApiError(401, "Mã mời không hợp lệ, đã dùng hoặc đã hết hạn"))).toContain("Mã mời");
    expect(authErrorMessage(new ApiError(401, "Unauthorized"), "Đăng nhập thất bại")).toBe("Đăng nhập thất bại");
    expect(authErrorMessage(new ApiError(429, "Thử đăng nhập quá nhiều lần; đợi vài phút"))).toContain("đợi vài phút");
    expect(authErrorMessage(new ApiError(0, "không gọi được backend: TypeError"))).toContain("Không kết nối được máy chủ");
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
