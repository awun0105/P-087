import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccountPage } from "@/features/studio/auth/AccountPage";
import { LoginForm, RegisterForm, safeNext } from "@/features/studio/auth/AuthForms";
import { AppShell } from "@/features/shell/AppShell";
import { TooltipProvider } from "@/components/shadcn/tooltip";
import { login, register, registerGuest, type Me } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

const state = vi.hoisted(() => ({ me: null as Me | null, refresh: vi.fn(), logout: vi.fn(), push: vi.fn(), replace: vi.fn(), search: "", pathname: "/overview" }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: state.push, replace: state.replace }), useSearchParams: () => new URLSearchParams(state.search), usePathname: () => state.pathname }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => state }));
vi.mock("@/lib/api/auth", async (original) => ({ ...(await original<typeof import("@/lib/api/auth")>()), login: vi.fn(), register: vi.fn(), registerGuest: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); state.me = { auth_required: true, user: null }; state.search = "next=%2Fnew%3Fsource%3Dvideo%26step%3Dsetup"; state.pathname = "/overview"; state.refresh.mockResolvedValue(undefined); });
describe("tài khoản và đích sau xác thực", () => {
  it("standard registration leaves invitation optional and creates a Guest when it is blank", async () => {
    state.me = { auth_required: true, user: null, guest_signup_enabled: true };
    vi.mocked(register).mockResolvedValue({ user_id: "guest-1", email: "guest@example.com", display_name: "Guest", role: "guest", active: true, daily_job_quota: 10 });
    render(<RegisterForm />);
    expect(screen.getByLabelText("Mã mời")).not.toBeRequired();
    expect(screen.getByText("Mã mời không bắt buộc. Bỏ trống để đăng ký tài khoản Khách.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Tên hiển thị"), { target: { value: "Guest" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "guest@example.com" } });
    fireEvent.change(screen.getByLabelText(/Mật khẩu/), { target: { value: "fixture-password" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    await waitFor(() => expect(register).toHaveBeenCalledWith({ invite_code: undefined, email: "guest@example.com", display_name: "Guest", password: "fixture-password" }));
    expect(registerGuest).not.toHaveBeenCalled();
    expect(state.refresh).toHaveBeenCalled();
    expect(state.replace).toHaveBeenCalledWith("/new?source=video&step=setup");
  });
  it("local không bịa profile; khách có link quay lại account", () => {
    state.me = { auth_required: false, user: null };
    const view = render(<AccountPage />);
    expect(screen.getByText("Chế độ local — không có tài khoản")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Đăng xuất" })).toBeNull();
    state.me = { auth_required: true, user: null }; view.rerender(<AccountPage />);
    expect(screen.getByRole("link", { name: "Đăng nhập" })).toHaveAttribute("href", "/login?next=/account");
  });
  it("hiện /me thật, logout lỗi giữ thông báo và cho thử lại", async () => {
    state.me = { auth_required: true, user: { user_id: "fixture-user", email: "fixture@example.com", display_name: "Tài khoản fixture", role: "editor", active: true, daily_job_quota: 7 } };
    state.logout.mockRejectedValue(new Error("Không đăng xuất được"));
    render(<AccountPage />);
    expect(screen.getByText("fixture@example.com")).toBeInTheDocument();
    expect(screen.getByText("7 lần / 24 giờ")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Không đăng xuất được");
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeEnabled();
  });
  it("hiện Guest riêng, không nhầm thành Editor khi /me chưa trả quota", () => {
    state.me = {
      auth_required: true,
      user: { user_id: "guest-1", email: "guest@example.com", display_name: "Guest", role: "guest", active: true, daily_job_quota: 10 },
    };
    render(<AccountPage />);
    expect(screen.getByRole("heading", { name: "Guest" })).toBeInTheDocument();
    expect(screen.getByText("Chưa tải được số lượt Guest còn lại.")).toBeInTheDocument();
    expect(screen.getByText(/chỉ sửa scene mình tạo/)).toBeInTheDocument();
    expect(screen.queryByText("10 lần / 24 giờ")).toBeNull();
  });
  it("AppShell phân biệt role Guest và hiển thị quota/reset từ backend", async () => {
    state.me = {
      auth_required: true,
      user: { user_id: "guest-1", email: "guest@example.com", display_name: "Guest Test", role: "guest", active: true, daily_job_quota: 10 },
      quota: {
        policy_id: "guest_calendar_day_v1",
        limit: 3,
        used: 1,
        remaining: 2,
        window_start_utc: "2026-10-07T17:00:00Z",
        resets_at_utc: "2026-10-08T17:00:00Z",
        timezone: "Asia/Ho_Chi_Minh",
      },
    };
    state.pathname = "/overview";
    render(<TooltipProvider><AppShell><div>Overview</div></AppShell></TooltipProvider>);
    fireEvent.pointerDown(screen.getByRole("button", { name: /Guest Test/ }), { button: 0, ctrlKey: false });
    expect(screen.getByText("Guest", { selector: "span" })).toBeInTheDocument();
    expect(await screen.findByText("Guest còn 2/3 lượt hôm nay.")).toBeInTheDocument();
    const reset = screen.getByText(/Đã dùng 1\/3; đặt lại lúc/);
    expect(reset).toHaveTextContent("00:00");
    expect(reset).toHaveTextContent("09/10/2026");
  });
  it("đăng nhập giữ đích tạo scene, link đăng ký và mẫu phân biệt rõ", async () => {
    vi.mocked(login).mockResolvedValue({ user_id: "fixture", email: "fixture@example.com", display_name: "Fixture", role: "editor", active: true, daily_job_quota: 10 });
    render(<LoginForm />);
    expect(screen.getByRole("link", { name: "Tạo tài khoản" })).toHaveAttribute("href", "/register?next=%2Fnew%3Fsource%3Dvideo%26step%3Dsetup");
    expect(screen.getByRole("link", { name: "Thử với video mẫu" })).toHaveAttribute("href", "/new/try-demo");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "fixture@example.com" } });
    fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: "fixture-password" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    // Thay entry của màn đăng nhập (không push): Back từ đích không rơi lại vào /login.
    await waitFor(() => expect(state.replace).toHaveBeenCalledWith("/new?source=video&step=setup"));
    expect(state.push).not.toHaveBeenCalled();
  });
  it("sai mật khẩu / mã mời hỏng: hiện đúng lý do backend trả, không báo 'phiên hết hạn'", async () => {
    vi.mocked(login).mockRejectedValue(new ApiError(401, "Sai email hoặc mật khẩu"));
    const view = render(<LoginForm />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "fixture@example.com" } });
    fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: "sai-mat-khau" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    expect(await screen.findByText("Sai email hoặc mật khẩu")).toBeInTheDocument();
    expect(screen.queryByText(/Phiên đăng nhập đã hết hạn/)).toBeNull();
    expect(state.push).not.toHaveBeenCalled();
    expect(state.replace).not.toHaveBeenCalled();
    view.unmount();

    vi.mocked(register).mockRejectedValue(new ApiError(401, "Mã mời không hợp lệ, đã dùng hoặc đã hết hạn"));
    render(<RegisterForm />);
    fireEvent.change(screen.getByLabelText("Mã mời"), { target: { value: "ma-da-dung" } });
    fireEvent.change(screen.getByLabelText("Tên hiển thị"), { target: { value: "Fixture" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "fixture@example.com" } });
    fireEvent.change(screen.getByLabelText(/Mật khẩu/), { target: { value: "fixture-password" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    expect(await screen.findByText("Mã mời không hợp lệ, đã dùng hoặc đã hết hạn")).toBeInTheDocument();
  });
  it("cửa vào app: đã đăng nhập hoặc chế độ local thì chuyển thẳng tới đích, không vẽ form", () => {
    const user = { user_id: "fixture", email: "fixture@example.com", display_name: "Fixture", role: "editor" as const, active: true, daily_job_quota: 10 };
    // Đang đọc phiên: chưa biết có cần đăng nhập không → không vẽ form, không chuyển hướng.
    state.me = null;
    const loading = render(<LoginForm />);
    expect(screen.getByRole("status")).toHaveTextContent("Đang kiểm tra phiên đăng nhập");
    expect(screen.queryByLabelText("Email")).toBeNull();
    expect(state.replace).not.toHaveBeenCalled();
    loading.unmount();

    // Đã đăng nhập: CTA của landing đi qua /login nhưng người dùng tới thẳng đích.
    state.me = { auth_required: true, user };
    const signedIn = render(<LoginForm />);
    expect(state.replace).toHaveBeenCalledTimes(1);
    expect(state.replace).toHaveBeenCalledWith("/new?source=video&step=setup");
    expect(screen.queryByLabelText("Email")).toBeNull();
    signedIn.unmount();

    // Chế độ local (không bật đăng nhập): không có tài khoản để đăng nhập → vào thẳng app; thiếu next thì về Tổng quan.
    state.replace.mockClear();
    state.search = "";
    state.me = { auth_required: false, user: null };
    const local = render(<LoginForm />);
    expect(state.replace).toHaveBeenCalledWith("/overview");
    local.unmount();

    state.replace.mockClear();
    state.me = { auth_required: true, user };
    render(<RegisterForm />);
    expect(state.replace).toHaveBeenCalledWith("/overview");
    expect(screen.queryByLabelText("Mã mời")).toBeNull();
  });
  it("đăng ký giữ next và từ chối đích chuyển ra ngoài", () => {
    render(<RegisterForm />);
    expect(screen.getByRole("link", { name: /Đăng nhập/ })).toHaveAttribute("href", expect.stringContaining("next="));
    expect(register).not.toHaveBeenCalled();
    expect(safeNext("/\\evil.example")).toBe("/overview");
    expect(safeNext("/path\n")).toBe("/overview");
  });

  it("Guest đăng ký theo endpoint riêng, không gửi invite hoặc role và chỉ hiện khi deployment bật", async () => {
    state.me = { auth_required: true, user: null, guest_signup_enabled: true };
    state.search = "mode=guest&next=%2Fscenes";
    vi.mocked(registerGuest).mockResolvedValue({
      user_id: "guest-1",
      email: "guest@example.com",
      display_name: "Guest",
      role: "guest",
      active: true,
      daily_job_quota: 10,
    });

    const view = render(<RegisterForm />);
    expect(screen.getByRole("heading", { name: "Tạo tài khoản Guest" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Mã mời")).toBeNull();
    fireEvent.change(screen.getByLabelText("Tên hiển thị"), { target: { value: "Guest" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "guest@example.com" } });
    fireEvent.change(screen.getByLabelText(/Mật khẩu/), { target: { value: "fixture-password" } });
    fireEvent.submit(screen.getByLabelText("Email").closest("form")!);
    await waitFor(() => expect(registerGuest).toHaveBeenCalledWith({
      email: "guest@example.com",
      display_name: "Guest",
      password: "fixture-password",
    }));
    expect(register).not.toHaveBeenCalled();
    expect(state.replace).toHaveBeenCalledWith("/scenes");
    view.unmount();

    state.me = { auth_required: true, user: null, guest_signup_enabled: false };
    render(<RegisterForm />);
    expect(screen.getByText("Đăng ký Guest hiện chưa được mở trên deployment này.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).toBeNull();
    expect(registerGuest).toHaveBeenCalledTimes(1);
  });

  it("AppShell: khách vào route workspace bị chuyển hướng về /login và không render nội dung", async () => {
    state.me = { auth_required: true, user: null };
    state.pathname = "/scenes";
    render(<AppShell><div data-testid="protected-content">Secret Scenes</div></AppShell>);
    expect(screen.queryByTestId("protected-content")).toBeNull();
    expect(state.replace).toHaveBeenCalledWith("/login?next=%2Fscenes");
  });

  it("AppShell: khách vào /new/try-demo được xem và thanh bên chỉ hiện video mẫu, không hiện workspace", () => {
    state.me = { auth_required: true, user: null };
    state.pathname = "/new/try-demo";
    render(<TooltipProvider><AppShell><div data-testid="demo-content">Demo Page</div></AppShell></TooltipProvider>);
    expect(screen.getByTestId("demo-content")).toBeInTheDocument();
    expect(state.replace).not.toHaveBeenCalled();
    // Sidebar không lộ các mục workspace
    expect(screen.queryByRole("link", { name: "Tổng quan" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Tạo scene mới" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Scenes" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Thùng rác" })).toBeNull();
    // Sidebar chỉ hiện Thử video mẫu và Đăng nhập
    const demoLinks = screen.getAllByRole("link", { name: "Thử video mẫu" });
    expect(demoLinks.some((link) => link.getAttribute("href") === "/new/try-demo")).toBe(true);
    expect(screen.getByRole("link", { name: "Đăng nhập" })).toHaveAttribute("href", "/login?next=%2Fnew%2Ftry-demo");
  });
});
