/** AuthProvider: kiểm tra phiên có hạn chờ, backend treo không giữ mãi màn "đang kiểm tra phiên". */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/features/studio/AuthProvider";

function Probe() {
  const { me } = useAuth();
  return <p>{me === null ? "đang kiểm tra" : me.user ? "đã đăng nhập" : "khách"}</p>;
}

afterEach(() => vi.restoreAllMocks());

describe("AuthProvider", () => {
  it("backend treo: hết hạn chờ thì báo lỗi có nút thử lại và coi như khách", async () => {
    const deadline = new AbortController();
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(deadline.signal);
    // Backend không bao giờ trả lời; fetch chỉ kết thúc khi signal của hạn chờ bị hủy.
    global.fetch = vi.fn((_url, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("timeout", "TimeoutError")));
    })) as typeof fetch;

    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(timeout).toHaveBeenCalledWith(10_000);
    expect(screen.getByText("đang kiểm tra")).toBeInTheDocument();

    deadline.abort();

    expect(await screen.findByRole("alert")).toHaveTextContent("Chưa xác minh được phiên tài khoản. Không kết nối được máy chủ");
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
    expect(screen.getByText("khách")).toBeInTheDocument();
  });
});
