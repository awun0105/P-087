"use client";

import { authErrorMessage } from "@/lib/ui-error";

import { Eye, EyeOff, Loader2 } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { Notice } from "@/components/studio/primitives";
import { PaletteMenu } from "@/features/shell/PaletteMenu";
import { ThemeToggle } from "@/features/shell/ThemeToggle";
import { useAuth } from "@/features/studio/AuthProvider";
import { notifySuccess, FieldError } from "@/components/studio/feedback";
import { login, register, registerGuest } from "@/lib/api/auth";
import { APP_HOME } from "@/lib/routes";
import { BrandIcon } from "@/components/studio/primitives";

/** Chỉ cho quay lại đường dẫn nội bộ (tránh open redirect qua `?next=`); thiếu/không hợp lệ thì về Tổng quan của app. */
export function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u001f]/.test(value)) return APP_HOME;
  return value;
}

/**
 * Màn đăng nhập/đăng ký là cửa vào app từ landing. Ai không cần qua cửa — đã đăng nhập, hoặc deployment không bật
 * đăng nhập (chế độ local, không có tài khoản nào để đăng nhập) — được chuyển thẳng tới đích. Trả `true` khi
 * chưa nên vẽ form: đang đọc phiên (`me === null`) hoặc đang chuyển đi.
 */
function useEntryGate(next: string): { pending: boolean; markNavigated: () => void } {
  const router = useRouter();
  const { me } = useAuth();
  const navigated = useRef(false);
  const passThrough = me !== null && (!me.auth_required || me.user !== null);
  useEffect(() => {
    if (!passThrough || navigated.current) return;
    navigated.current = true;
    router.replace(next);
  }, [passThrough, next, router]);
  return { pending: me === null || passThrough, markNavigated: () => { navigated.current = true; } };
}

function useFieldValidation() {
  const [fieldErrors, setErrors] = useState<Record<string, string>>({});
  function validate(event: React.SyntheticEvent<HTMLFormElement>) {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;
    const message = input.validity.valid
      ? ""
      : input.validity.typeMismatch
        ? "Nhập email đúng định dạng."
        : input.validity.tooShort
          ? "Mật khẩu cần ít nhất 10 ký tự."
          : "Điền thông tin bắt buộc.";
    setErrors((old) => ({ ...old, [input.id]: message }));
  }
  return { fieldErrors, validate };
}

/**
 * Khung layout theo tham chiếu Lovable và hệ thống Stitch design system:
 * - Cột trái: Header logo dạng dot, tiêu đề trang, form input underline (border-b), nút pill và chuyển trang.
 * - Cột phải: Hero showcase LiDAR Warehouse với scrim gradient và slogan "From reality. To simulation."
 */
function Shell({
  title,
  lead,
  children,
  mode,
  next,
}: {
  title: string;
  lead: string;
  children: React.ReactNode;
  mode: "login" | "register";
  next: string;
}) {
  return (
    <main className="grid min-h-dvh overflow-x-hidden bg-background text-foreground lg:grid-cols-2">
      {/* Cột trái: Form & Header */}
      <section className="relative flex min-h-dvh min-w-0 flex-col bg-background px-6 py-7 sm:px-10 sm:py-9 lg:px-[clamp(3.5rem,5vw,5.25rem)] lg:py-10">
        <header className="flex items-center justify-between gap-4">
          <Link
            href="/"
            className="flex min-w-0 items-center gap-3 transition-opacity hover:opacity-90"
            aria-label="Real2Sim Studio Trang chủ"
          >
            <BrandIcon className="size-8 shrink-0" />
            <div className="flex items-baseline gap-1.5">
              <span className="font-display text-lg font-bold tracking-tight text-foreground">
                Real2Sim
              </span>
              <span className="rounded border border-line bg-paper-sunken px-1.5 py-0.5 font-mono text-[11px] leading-none font-semibold tracking-widest text-ink-muted uppercase">
                Studio
              </span>
            </div>
          </Link>
          <div className="flex items-center gap-1.5">
            <PaletteMenu />
            <ThemeToggle />
          </div>
        </header>

        <div className="flex w-full flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[420px]">
            <h1 className="font-display text-[clamp(2.25rem,3.2vw,3rem)] font-semibold leading-none tracking-normal text-foreground">
              {title}
            </h1>
            <p className="mt-4 font-ui text-[15px] leading-7 text-muted-foreground">
              {lead}
            </p>

            <div className="mt-8">{children}</div>

            {mode === "login" ? (
              <>
                <p className="mt-6 text-center font-ui text-sm text-muted-foreground">
                  Chưa có tài khoản?{" "}
                  <Link
                    href={"/register?next=" + encodeURIComponent(next)}
                    className="font-semibold text-foreground underline decoration-border underline-offset-4 transition-colors hover:decoration-primary"
                  >
                    Tạo tài khoản
                  </Link>
                </p>
                <p className="mt-3 text-center font-ui text-xs text-muted-foreground">
                  Khách có thể{" "}
                  <Link
                    href="/new/try-demo"
                    className="font-medium text-foreground underline decoration-border underline-offset-4 transition-colors hover:decoration-primary"
                  >
                    Thử với video mẫu
                  </Link>{" "}
                  — không cần đăng nhập.
                </p>
              </>
            ) : (
              <p className="mt-6 text-center font-ui text-sm text-muted-foreground">
                Đã có tài khoản?{" "}
                <Link
                  href={"/login?next=" + encodeURIComponent(next)}
                  className="font-semibold text-foreground underline decoration-border underline-offset-4 transition-colors hover:decoration-primary"
                >
                  Đăng nhập
                </Link>
              </p>
            )}
          </div>
        </div>
      </section>

      {/* Cột phải: Hero showcase LiDAR Warehouse */}
      <aside
        className="hidden min-h-dvh min-w-0 bg-background p-4 pl-0 lg:block"
        aria-label="Mô phỏng tái tạo nhà kho bằng LiDAR"
      >
        <div className="relative h-full min-h-[calc(100dvh-2rem)] overflow-hidden rounded-[22px] bg-hero">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt="Robot tự hành trong nhà kho chuyển đổi thành mô hình tái tạo 3D"
            width={1536}
            height={1536}
            className="absolute inset-0 size-full object-cover"
            src="/real2sim-warehouse.jpg"
          />
          <div className="bg-hero-scrim absolute inset-0" />
          <div className="absolute right-0 bottom-0 left-0 p-10 xl:p-14">
            <h2 className="font-display max-w-2xl text-4xl font-semibold leading-[1.02] tracking-normal text-hero-foreground xl:text-5xl">
              From reality.
              <br />
              To simulation.
            </h2>
            <p className="font-ui text-hero-muted mt-4 max-w-sm text-sm leading-6">
              Transform RGB video and LiDAR data into simulation-ready environments.
            </p>
          </div>
        </div>
      </aside>
    </main>
  );
}

/** Đang đọc phiên hoặc đang chuyển tới đích: giữ khung trang, không nháy form cho người không cần đăng nhập. */
function EntryPending() {
  return (
    <main className="grid min-h-dvh place-items-center bg-background text-foreground" role="status" aria-live="polite">
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        Đang kiểm tra phiên đăng nhập…
      </p>
    </main>
  );
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useAuth();
  const next = safeNext(params.get("next"));
  const gate = useEntryGate(next);
  const { fieldErrors, validate } = useFieldValidation();
  const ids = { email: useId(), password: useId() };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      gate.markNavigated();
      await refresh();
      notifySuccess("Đã đăng nhập.");
      router.replace(next);
    } catch (cause) {
      setError(authErrorMessage(cause, "Đăng nhập thất bại"));
      setBusy(false);
    }
  }

  if (gate.pending && !busy) return <EntryPending />;
  return (
    <Shell
      title="Đăng nhập"
      lead="Truy cập workspace mô phỏng và quản lý các scene của bạn."
      mode="login"
      next={next}
    >
      <form
        onInvalid={validate}
        onBlurCapture={validate}
        onChangeCapture={validate}
        onSubmit={submit}
        className="space-y-5"
      >
        <div className="space-y-1.5">
          <label
            className="block font-ui text-xs font-semibold text-foreground/90"
            htmlFor={ids.email}
          >
            Email
          </label>
          <input
            id={ids.email}
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="engineer@domain.com"
            aria-invalid={!!fieldErrors[ids.email]}
            aria-describedby={fieldErrors[ids.email] ? ids.email + "-error" : undefined}
            className="h-11 w-full rounded-xl border border-line-strong/60 bg-paper-raised/70 px-3.5 font-ui text-sm text-foreground shadow-xs outline-none transition-all placeholder:text-foreground/40 hover:border-line-strong focus:border-primary focus:bg-background focus:ring-3 focus:ring-primary/20"
          />
          <FieldError id={ids.email + "-error"} message={fieldErrors[ids.email] ?? null} />
        </div>

        <div className="space-y-1.5">
          <label
            className="block font-ui text-xs font-semibold text-foreground/90"
            htmlFor={ids.password}
          >
            Mật khẩu
          </label>
          <div className="relative flex h-11 w-full items-center rounded-xl border border-line-strong/60 bg-paper-raised/70 shadow-xs transition-all hover:border-line-strong focus-within:border-primary focus-within:bg-background focus-within:ring-3 focus-within:ring-primary/20">
            <input
              id={ids.password}
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              minLength={8}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              aria-invalid={!!fieldErrors[ids.password]}
              aria-describedby={fieldErrors[ids.password] ? ids.password + "-error" : undefined}
              className="h-full w-full rounded-xl bg-transparent pl-3.5 pr-10 font-ui text-sm text-foreground outline-none placeholder:text-foreground/40"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              title={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              className="absolute right-1 flex size-9 items-center justify-center rounded-lg text-foreground/50 transition-colors hover:text-foreground"
            >
              {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            </button>
          </div>
          <FieldError id={ids.password + "-error"} message={fieldErrors[ids.password] ?? null} />
        </div>

        {error && <Notice tone="rust">{error}</Notice>}

        <button
          type="submit"
          disabled={busy}
          className="mt-6 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 font-ui text-sm font-semibold text-primary-foreground shadow-sm transition-all hover:bg-primary-hover hover:shadow focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/30 disabled:pointer-events-none disabled:opacity-60"
        >
          {busy && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />}
          <span>Đăng nhập</span>
        </button>
      </form>
    </Shell>
  );
}

export function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { me, refresh } = useAuth();
  const guestMode = params.get("mode") === "guest";
  const guestSignupEnabled = me?.guest_signup_enabled === true;
  const next = safeNext(params.get("next"));
  const gate = useEntryGate(next);
  const { fieldErrors, validate } = useFieldValidation();
  const ids = { code: useId(), name: useId(), email: useId(), password: useId() };
  const [code, setCode] = useState(params.get("code") ?? "");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const user = guestMode
        ? await registerGuest({ email, display_name: name.trim(), password })
        : await register({ invite_code: code.trim() || undefined, email, display_name: name.trim(), password });
      gate.markNavigated();
      await refresh();
      notifySuccess(user.role === "guest" ? "Đã tạo tài khoản Guest và đăng nhập." : "Đã tạo tài khoản và đăng nhập.");
      router.replace(next);
    } catch (cause) {
      setError(authErrorMessage(cause, "Không tạo được tài khoản"));
      setBusy(false);
    }
  }

  if (gate.pending && !busy) return <EntryPending />;
  if (guestMode && me?.guest_signup_enabled !== true) {
    return (
      <Shell
        title="Đăng ký Guest"
        lead="Đăng ký Guest hiện chưa được mở trên deployment này."
        mode="register"
        next={next}
      >
        <Notice tone="ochre">Khi được mở, Guest sẽ tạo tài khoản không cần mã mời. Luồng này không xác minh email qua thư.</Notice>
        <p className="mt-5 text-center text-sm text-muted-foreground">
          Có mã mời?{" "}
          <Link href={`/register?next=${encodeURIComponent(next)}`} className="font-semibold text-foreground underline underline-offset-4">
            Đăng ký bằng mã mời
          </Link>
        </p>
      </Shell>
    );
  }
  return (
    <Shell
      title={guestMode ? "Tạo tài khoản Guest" : "Tạo tài khoản"}
      lead={
        guestMode
          ? "Nhập email, tên hiển thị và mật khẩu. Email chưa được xác minh qua thư."
          : guestSignupEnabled ? "Không có mã mời, bạn sẽ được tạo tài khoản Khách (Guest). Có mã mời, quyền được cấp theo lời mời." : "Nhập mã mời do Reviewer của nhóm gửi. Mã chỉ dùng được một lần."
      }
      mode="register"
      next={next}
    >
      <form
        onInvalid={validate}
        onBlurCapture={validate}
        onChangeCapture={validate}
        onSubmit={submit}
        className="space-y-5"
      >
        {!guestMode && <div className="space-y-1.5">
          <label
            className="block font-ui text-xs font-semibold text-foreground/90"
            htmlFor={ids.code}
          >
            Mã mời
          </label>
          <input
            id={ids.code}
            name="code"
            required={!guestSignupEnabled}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoComplete="off"
            placeholder="inv_..."
            aria-invalid={!!fieldErrors[ids.code]}
            aria-describedby={fieldErrors[ids.code] ? ids.code + "-error" : guestSignupEnabled ? ids.code + "-hint" : undefined}
            className="h-11 w-full rounded-xl border border-line-strong/60 bg-paper-raised/70 px-3.5 font-ui text-sm text-foreground shadow-xs outline-none transition-all placeholder:text-foreground/40 hover:border-line-strong focus:border-primary focus:bg-background focus:ring-3 focus:ring-primary/20"
          />
          <FieldError id={ids.code + "-error"} message={fieldErrors[ids.code] ?? null} />
          {guestSignupEnabled && <p id={ids.code + "-hint"} className="text-xs text-muted-foreground">Mã mời không bắt buộc. Bỏ trống để đăng ký tài khoản Khách.</p>}
        </div>}

        <div className="space-y-1.5">
          <label
            className="block font-ui text-xs font-semibold text-foreground/90"
            htmlFor={ids.name}
          >
            Tên hiển thị
          </label>
          <input
            id={ids.name}
            name="name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            placeholder="Robot Engineer"
            aria-invalid={!!fieldErrors[ids.name]}
            aria-describedby={fieldErrors[ids.name] ? ids.name + "-error" : undefined}
            className="h-11 w-full rounded-xl border border-line-strong/60 bg-paper-raised/70 px-3.5 font-ui text-sm text-foreground shadow-xs outline-none transition-all placeholder:text-foreground/40 hover:border-line-strong focus:border-primary focus:bg-background focus:ring-3 focus:ring-primary/20"
          />
          <FieldError id={ids.name + "-error"} message={fieldErrors[ids.name] ?? null} />
        </div>

        <div className="space-y-1.5">
          <label
            className="block font-ui text-xs font-semibold text-foreground/90"
            htmlFor={ids.email}
          >
            Email
          </label>
          <input
            id={ids.email}
            name="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            placeholder="engineer@domain.com"
            aria-invalid={!!fieldErrors[ids.email]}
            aria-describedby={fieldErrors[ids.email] ? ids.email + "-error" : undefined}
            className="h-11 w-full rounded-xl border border-line-strong/60 bg-paper-raised/70 px-3.5 font-ui text-sm text-foreground shadow-xs outline-none transition-all placeholder:text-foreground/40 hover:border-line-strong focus:border-primary focus:bg-background focus:ring-3 focus:ring-primary/20"
          />
          <FieldError id={ids.email + "-error"} message={fieldErrors[ids.email] ?? null} />
        </div>

        <div className="space-y-1.5">
          <label
            className="block font-ui text-xs font-semibold text-foreground/90"
            htmlFor={ids.password}
          >
            Mật khẩu (ít nhất 10 ký tự)
          </label>
          <div className="relative flex h-11 w-full items-center rounded-xl border border-line-strong/60 bg-paper-raised/70 shadow-xs transition-all hover:border-line-strong focus-within:border-primary focus-within:bg-background focus-within:ring-3 focus-within:ring-primary/20">
            <input
              id={ids.password}
              name="password"
              type={showPassword ? "text" : "password"}
              minLength={10}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="••••••••••••"
              aria-invalid={!!fieldErrors[ids.password]}
              aria-describedby={fieldErrors[ids.password] ? ids.password + "-error" : undefined}
              className="h-full w-full rounded-xl bg-transparent pl-3.5 pr-10 font-ui text-sm text-foreground outline-none placeholder:text-foreground/40"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              title={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              className="absolute right-1 flex size-9 items-center justify-center rounded-lg text-foreground/50 transition-colors hover:text-foreground"
            >
              {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            </button>
          </div>
          <FieldError id={ids.password + "-error"} message={fieldErrors[ids.password] ?? null} />
        </div>

        {error && <Notice tone="rust">{error}</Notice>}

        <button
          type="submit"
          disabled={busy}
          className="mt-6 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 font-ui text-sm font-semibold text-primary-foreground shadow-sm transition-all hover:bg-primary-hover hover:shadow focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/30 disabled:pointer-events-none disabled:opacity-60"
        >
          {busy && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />}
          <span>{guestMode ? "Tạo tài khoản Guest" : "Tạo tài khoản"}</span>
        </button>
      </form>
      {guestMode && (
        <p className="mt-5 text-center text-sm text-muted-foreground">
          Có mã mời?{" "}
          <Link href={`/register?next=${encodeURIComponent(next)}`} className="font-semibold text-foreground underline underline-offset-4">
            Dùng luồng đăng ký mời
          </Link>
        </p>
      )}
    </Shell>
  );
}
