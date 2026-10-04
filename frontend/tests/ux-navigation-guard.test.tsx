import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NavigationGuardProvider, useNavigationGuard } from "@/features/shell/NavigationGuard";
import { queryEditorDirty } from "@/features/studio/editor-dirty";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
beforeEach(() => { history.replaceState({ __NA: true }, "", "/other"); });
function Client({ dirty }: { dirty: () => Promise<boolean> }) {
  const guard = useNavigationGuard();
  const { register } = guard;
  useEffect(() => register({ dirty, warnOnUnload: () => true, releases: (href) => new URL(href, location.href).pathname === "/other" }), [register, dirty]);
  return <button onClick={() => void guard.navigate(() => history.pushState({ __NA: true }, "", "/other"), "/other")}>Rời editor</button>;
}
describe("guard phiên editor", () => {
  it("iframe dirty giữ phiên khi cancel, chỉ navigate sau xác nhận", async () => {
    history.replaceState({ __NA: true }, "", "/editor-host");
    render(<NavigationGuardProvider><Client dirty={async () => true} /></NavigationGuardProvider>);
    fireEvent.click(screen.getByText("Rời editor"));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByText("Ở lại")); });
    expect(location.pathname).toBe("/editor-host");
    fireEvent.click(screen.getByText("Rời editor"));
    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByText("Rời và bỏ thay đổi"));
    await waitFor(() => expect(location.pathname).toBe("/other"));
    expect(history.state.__NA).toBe(true);
  });
  it("browser Back khôi phục entry nguồn trước khi hỏi; cancel giữ iframe route", async () => {
    render(<NavigationGuardProvider><Client dirty={async () => true} /></NavigationGuardProvider>);
    act(() => history.pushState({ __NA: true }, "", "/editor-host"));
    act(() => history.back());
    await screen.findByRole("alertdialog");
    expect(location.pathname).toBe("/editor-host");
    fireEvent.click(screen.getByText("Ở lại"));
    expect(location.pathname).toBe("/editor-host");
    act(() => history.back());
    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByText("Rời và bỏ thay đổi"));
    await waitFor(() => expect(location.pathname).toBe("/other"));
  });
  it("scene sạch không hỏi; UNKNOWN không tự bỏ phiên", async () => {
    const dirty = vi.fn().mockResolvedValueOnce(false).mockRejectedValueOnce(new Error("timeout"));
    history.replaceState({}, "", "/editor-host");
    render(<NavigationGuardProvider><Client dirty={dirty} /></NavigationGuardProvider>);
    fireEvent.click(screen.getByText("Rời editor"));
    await waitFor(() => expect(location.pathname).toBe("/other"));
    fireEvent.click(screen.getByText("Rời editor"));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
  });
  it("bridge bỏ message sai origin/source và chấp nhận boolean đúng iframe", async () => {
    const frame = { postMessage: vi.fn() } as unknown as Window;
    const dirty = queryEditorDirty(frame);
    window.dispatchEvent(new MessageEvent("message", { origin: "https://invalid.example", source: frame, data: { type: "supersplat:is-scene-dirty", result: false } }));
    window.dispatchEvent(new MessageEvent("message", { origin: location.origin, source: window, data: { type: "supersplat:is-scene-dirty", result: false } }));
    window.dispatchEvent(new MessageEvent("message", { origin: location.origin, source: frame, data: { type: "supersplat:is-scene-dirty", result: true } }));
    await expect(dirty).resolves.toBe(true);
  });
  it("unmount/abort bridge không giữ listener/promise", async () => {
    const controller = new AbortController();
    const frame = { postMessage: vi.fn() } as unknown as Window;
    const dirty = queryEditorDirty(frame, controller.signal);
    const expected = expect(dirty).rejects.toThrow("Chưa kiểm tra");
    controller.abort();
    await expected;
  });
});
