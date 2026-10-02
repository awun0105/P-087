/** Thùng rác: chọn từng mục / nhiều mục / tất cả, khôi phục, và xoá hẳn phải qua xác nhận + chỉ Reviewer. */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MoveToTrashButton } from "@/features/studio/trash/MoveToTrashButton";
import { remainingLabel, TrashPage } from "@/features/studio/trash/TrashPage";
import type { Me } from "@/lib/api/auth";
import { parseTrashEntries } from "@/lib/api/studio";

const auth = vi.hoisted(() => ({ me: { auth_required: false, user: null } as Me }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => auth }));

function entry(id: string, title: string) {
  return {
    entry_id: id, title, deleted_at: "2026-10-02T01:00:00Z", expires_at: "2026-10-09T01:00:00Z", deleted_by: null, size_bytes: 2_000_000,
    items: [{ kind: "scene", identifier: `project-${id}`, name: title, detail: "job-1 CANCELLED" }, { kind: "upload", identifier: `upload-${id}`, name: "walk.mp4", detail: "" }],
  };
}

function reply(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

/** Backend giả: giữ danh sách thùng rác và ghi lại các lệnh nhận được. */
function backend(initial: ReturnType<typeof entry>[], failing: string[] = []) {
  let entries = [...initial];
  const calls: { url: string; ids: string[] }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const ids = (JSON.parse(String(init.body)) as { entry_ids: string[] }).entry_ids;
      calls.push({ url, ids });
      const done = ids.filter((id) => !failing.includes(id));
      entries = entries.filter((item) => !done.includes(item.entry_id));
      return reply({ done, failed: ids.filter((id) => failing.includes(id)).map((id) => ({ entry_id: id, reason: "vị trí đang dùng đã có dữ liệu khác" })) });
    }
    return reply({ entries });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

describe("TrashPage", () => {
  beforeEach(() => { auth.me = { auth_required: false, user: null }; vi.unstubAllGlobals(); });

  it("thùng rác trống hiện trạng thái rỗng, không có nút hàng loạt", async () => {
    backend([]);
    render(<TrashPage />);
    expect(await screen.findByText("Thùng rác trống")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Xoá tất cả/ })).toBeNull();
  });

  it("khôi phục một mục gửi đúng ID và mục đó rời danh sách", async () => {
    const calls = backend([entry("a", "Kho A"), entry("b", "Kho B")]);
    render(<TrashPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Khôi phục Kho A" }));
    await waitFor(() => expect(screen.queryByText("Kho A")).toBeNull());
    expect(calls).toEqual([{ url: "/api/v1/trash/restore", ids: ["a"] }]);
    expect(screen.getByText("Kho B")).toBeInTheDocument();
  });

  it("chọn nhiều mục rồi xoá hẳn: phải xác nhận, huỷ thì không gửi gì", async () => {
    const calls = backend([entry("a", "Kho A"), entry("b", "Kho B"), entry("c", "Kho C")]);
    render(<TrashPage />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Chọn Kho A" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn Kho C" }));
    expect(screen.getByText("Đã chọn 2/3 mục")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Xoá hẳn mục đã chọn/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Xoá hẳn 2 mục?")).toBeInTheDocument();
    expect(within(dialog).getByText(/không khôi phục được/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Giữ lại" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(calls).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: /Xoá hẳn mục đã chọn/ }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Xoá hẳn" }));
    await waitFor(() => expect(screen.queryByText("Kho A")).toBeNull());
    expect(calls).toEqual([{ url: "/api/v1/trash/purge", ids: ["a", "c"] }]);
    expect(screen.getByText("Kho B")).toBeInTheDocument();
  });

  it("chọn tất cả và khôi phục tất cả; mục lỗi được nêu tên kèm lý do", async () => {
    const calls = backend([entry("a", "Kho A"), entry("b", "Kho B")], ["b"]);
    render(<TrashPage />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Chọn tất cả" }));
    expect(screen.getByText("Đã chọn 2/2 mục")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Khôi phục tất cả/ }));
    expect(await screen.findByText(/Kho B: vị trí đang dùng đã có dữ liệu khác/)).toBeInTheDocument();
    expect(calls).toEqual([{ url: "/api/v1/trash/restore", ids: ["a", "b"] }]);
    expect(screen.queryByRole("button", { name: "Khôi phục Kho A" })).toBeNull();
    expect(screen.getByRole("button", { name: "Khôi phục Kho B" })).toBeInTheDocument();
  });

  it("Editor khôi phục được nhưng không xoá hẳn được", async () => {
    auth.me = { auth_required: true, user: { user_id: "u1", email: "e@x.dev", display_name: "E", role: "editor", daily_job_quota: 3 } } as Me;
    backend([entry("a", "Kho A")]);
    render(<TrashPage />);
    expect(await screen.findByRole("button", { name: "Xoá hẳn Kho A" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Xoá tất cả/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Khôi phục Kho A" })).toBeEnabled();
    expect(screen.getByText(/Chỉ Reviewer xoá hẳn được/)).toBeInTheDocument();
  });

  it("khách không tải thùng rác", async () => {
    auth.me = { auth_required: true, user: null };
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<TrashPage />);
    expect(screen.getByText("Đăng nhập để xem thùng rác")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("MoveToTrashButton", () => {
  it("chỉ gỡ sau khi xác nhận; lỗi backend hiện trong hộp thoại và không báo đã gỡ", async () => {
    const move = vi.fn().mockRejectedValueOnce(new Error("job đang chờ worker (QUEUED)")).mockResolvedValueOnce({});
    const onMoved = vi.fn();
    render(<MoveToTrashButton name="Kho A" move={move} onMoved={onMoved} />);
    fireEvent.click(screen.getByRole("button", { name: "Chuyển Kho A vào thùng rác" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(move).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Chuyển vào thùng rác" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("QUEUED");
    expect(onMoved).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Chuyển vào thùng rác" }));
    await waitFor(() => expect(onMoved).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });
});

describe("remainingLabel", () => {
  it("đếm ngày còn lại, làm tròn lên; quá hạn và tắt tự xoá có nhãn riêng", () => {
    const expires = "2026-10-09T01:00:00Z";
    expect(remainingLabel(expires, Date.parse("2026-10-02T01:00:00Z"))).toBe("Còn 7 ngày");
    expect(remainingLabel(expires, Date.parse("2026-10-08T12:00:00Z"))).toBe("Còn 1 ngày");
    expect(remainingLabel(expires, Date.parse("2026-10-09T02:00:00Z"))).toBe("Sắp bị xoá hẳn");
    expect(remainingLabel(null, 0)).toBe("Không tự xoá");
  });
});

describe("parseTrashEntries", () => {
  it("từ chối dữ liệu sai dạng thay vì hiện sai", () => {
    expect(parseTrashEntries({ entries: [entry("a", "Kho A")] })[0].items).toHaveLength(2);
    expect(() => parseTrashEntries({ entries: [{ entry_id: "a" }] })).toThrow();
    expect(() => parseTrashEntries({ entries: [{ ...entry("a", "A"), items: [{ kind: "khac", identifier: "x", name: "y" }] }] })).toThrow();
    expect(() => parseTrashEntries(null)).toThrow();
  });
});
