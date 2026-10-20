import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "@/features/studio/auth/AuthForms";
import { TRIAL_GUEST_KEY, startTrialGuest } from "@/features/studio/auth/trialGuest";
import { login, registerGuest, type Me, type PublicUser } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

const state = vi.hoisted(() => ({ me: null as Me | null, refresh: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: state.replace }), useSearchParams: () => new URLSearchParams("next=%2Fnew") }));
vi.mock("@/features/studio/AuthProvider", () => ({ useAuth: () => state }));
vi.mock("@/lib/api/auth", async (original) => ({ ...(await original<typeof import("@/lib/api/auth")>()), login: vi.fn(), registerGuest: vi.fn() }));

const GUEST: PublicUser = { user_id: "guest-1", email: "guest@try.real2sim.dev", display_name: "Khách dùng thử", role: "guest", active: true, daily_job_quota: 10 };

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  state.me = { auth_required: true, user: null, guest_signup_enabled: true };
  state.refresh.mockResolvedValue(undefined);
  vi.mocked(registerGuest).mockResolvedValue(GUEST);
  vi.mocked(login).mockResolvedValue(GUEST);
});

describe("Dùng thử ngay", () => {
  it("creates a private Guest once, remembers it, and signs back into the same account next time", async () => {
    await startTrialGuest();
    const created = vi.mocked(registerGuest).mock.calls[0][0];
    expect(created.email).toMatch(/^guest-[0-9a-f]{12}@try\.real2sim\.dev$/);
    expect(created.password).toMatch(/^[0-9a-f]{32}$/);
    expect(JSON.parse(window.localStorage.getItem(TRIAL_GUEST_KEY)!)).toEqual({ email: created.email, password: created.password });

    await startTrialGuest();
    expect(login).toHaveBeenCalledWith(created.email, created.password);
    expect(registerGuest).toHaveBeenCalledTimes(1);
  });

  it("replaces a remembered account the server no longer accepts, but never on a network error", async () => {
    window.localStorage.setItem(TRIAL_GUEST_KEY, JSON.stringify({ email: "guest-old@try.real2sim.dev", password: "old" }));
    vi.mocked(login).mockRejectedValueOnce(new ApiError(401, "Sai email hoặc mật khẩu"));
    await startTrialGuest();
    expect(registerGuest).toHaveBeenCalledTimes(1);

    vi.mocked(login).mockRejectedValueOnce(new ApiError(0, "không gọi được backend"));
    await expect(startTrialGuest()).rejects.toThrow("không gọi được backend");
    expect(registerGuest).toHaveBeenCalledTimes(1);
  });

  it("is offered on the login page only when the server opens Guest signup, and lands on the requested page", async () => {
    state.me = { auth_required: true, user: null, guest_signup_enabled: false };
    const view = render(<LoginForm />);
    expect(screen.queryByRole("button", { name: "Dùng thử ngay" })).toBeNull();

    state.me = { auth_required: true, user: null, guest_signup_enabled: true };
    view.rerender(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Dùng thử ngay" }));
    await waitFor(() => expect(state.replace).toHaveBeenCalledWith("/new"));
    expect(registerGuest).toHaveBeenCalledTimes(1);
    expect(state.refresh).toHaveBeenCalled();
  });
});
