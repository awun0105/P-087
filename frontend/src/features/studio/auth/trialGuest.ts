import { login, registerGuest, type PublicUser } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

/**
 * "Dùng thử ngay": mỗi trình duyệt một tài khoản Guest riêng, tạo ngầm bằng email và mật khẩu ngẫu nhiên.
 * Guest xem được mọi scene nhưng chỉ sửa được scene của chính mình và có hạn mức ngày do máy chủ giữ, nên không
 * ai đụng được scene của nhóm. Thông tin đăng nhập nằm trong localStorage của trình duyệt để lần sau quay lại vẫn là tài khoản đó;
 * mất localStorage thì chỉ là tạo tài khoản mới.
 */
export const TRIAL_GUEST_KEY = "r2s-trial-guest";
const TRIAL_EMAIL_DOMAIN = "try.real2sim.dev";

interface TrialCredentials {
  email: string;
  password: string;
}

/** Tài khoản do "Dùng thử ngay" tạo (email ngẫu nhiên trên miền riêng), để trang hồ sơ giải thích nó gắn với trình duyệt. */
export function isTrialGuest(email: string): boolean {
  return email.endsWith(`@${TRIAL_EMAIL_DOMAIN}`);
}

function randomToken(bytes: number): string {
  const values = crypto.getRandomValues(new Uint8Array(bytes));
  return Array.from(values, (value) => value.toString(16).padStart(2, "0")).join("");
}

function readSaved(): TrialCredentials | null {
  try {
    const raw = window.localStorage.getItem(TRIAL_GUEST_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed === "object" && "email" in parsed && "password" in parsed) {
      const { email, password } = parsed as Record<string, unknown>;
      if (typeof email === "string" && typeof password === "string") return { email, password };
    }
  } catch {
    // Trình duyệt chặn storage hoặc dữ liệu hỏng: tạo tài khoản mới.
  }
  return null;
}

function save(credentials: TrialCredentials | null): void {
  try {
    if (credentials) window.localStorage.setItem(TRIAL_GUEST_KEY, JSON.stringify(credentials));
    else window.localStorage.removeItem(TRIAL_GUEST_KEY);
  } catch {
    // Không lưu được thì lần sau tạo tài khoản khác; phiên hiện tại vẫn đăng nhập.
  }
}

/** Đăng nhập lại tài khoản dùng thử của trình duyệt này, hoặc tạo mới nếu chưa có / đã bị xóa hay khóa. */
export async function startTrialGuest(): Promise<PublicUser> {
  const saved = readSaved();
  if (saved) {
    try {
      return await login(saved.email, saved.password);
    } catch (cause) {
      // 401/403: tài khoản không còn dùng được. Lỗi khác (mạng, 429) thì báo lên, không tạo thêm tài khoản.
      if (!(cause instanceof ApiError) || (cause.status !== 401 && cause.status !== 403)) throw cause;
      save(null);
    }
  }
  const credentials = { email: `guest-${randomToken(6)}@${TRIAL_EMAIL_DOMAIN}`, password: randomToken(16) };
  const user = await registerGuest({ ...credentials, display_name: "Khách dùng thử" });
  save(credentials);
  return user;
}
