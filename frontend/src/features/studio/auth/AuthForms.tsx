"use client";

import { errorMessage } from "@/lib/ui-error";

import { Box, Loader2, LogIn, UserPlus } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useRouter, useSearchParams } from "next/navigation";
import { cloneElement, isValidElement, useId, useState, type ComponentProps } from "react";

import { Input } from "@/components/shadcn/input";
import { Label } from "@/components/shadcn/label";
import { Button, Notice } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { notifySuccess, FieldError } from "@/components/studio/feedback";
import { login, register } from "@/lib/api/auth";

const INPUT = "mt-1.5 h-10";

/** Chỉ cho quay lại đường dẫn nội bộ (tránh open redirect qua `?next=`). */
export function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u001f]/.test(value)) return "/";
  return value;
}

function Field({ id, label, children, error }: { id: string; label: string; children: React.ReactNode; error?: string }) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      {isValidElement<ComponentProps<"input">>(children) ? cloneElement(children, { "aria-invalid": !!error, "aria-describedby": error ? id + "-error" : undefined }) : children}
      <FieldError id={id + "-error"} message={error ?? null} />
    </div>
  );
}

function useFieldValidation() {
  const [fieldErrors, setErrors] = useState<Record<string, string>>({});
  function validate(event: React.SyntheticEvent<HTMLFormElement>) {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;
    const message = input.validity.valid ? "" : input.validity.typeMismatch ? "Nhập email đúng định dạng." : input.validity.tooShort ? "Mật khẩu cần ít nhất 10 ký tự." : "Điền thông tin bắt buộc.";
    setErrors((old) => ({ ...old, [input.id]: message }));
  }
  return { fieldErrors, validate };
}

const STEPS = [
  "Video camera di chuyển chậm trong kho",
  "Scene 3D Gaussian Splatting, quy đổi sang mét",
  "Collision mesh và vật thể bạn xác nhận",
  "Gói OpenUSD cho Isaac Sim, qua duyệt trước khi phát hành",
];

/**
 * Layout đăng nhập/mã mời theo auth v2 của dashboard donor (PRODUCT.md S02): form bên trái,
 * panel giới thiệu luồng thật bên phải; không SSO, không chọn role, không số liệu quảng cáo.
 */
function Shell({ title, lead, children }: { title: string; lead: string; children: React.ReactNode }) {
  return (
    <main className="grid min-h-dvh bg-paper p-2 text-ink lg:grid-cols-2">
      <div className="flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm">
          <Link href="/" className="mb-10 flex items-center gap-2 font-semibold">
            <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
              <Box className="size-4" aria-hidden />
            </span>
            Real2Sim Studio
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-2 text-sm text-ink-muted">{lead}</p>
          <div className="mt-8">{children}</div>
          <p className="mt-8 text-sm text-ink-muted">
            Chưa có tài khoản?{" "}
            <Link href="/new?source=sample" className="font-medium text-ember-strong underline-offset-4 hover:underline">
              Thử với video mẫu
            </Link>{" "}
            — không cần đăng nhập.
          </p>
        </div>
      </div>
      <aside className="relative hidden flex-col justify-between rounded-3xl bg-paper-raised p-10 lg:flex" aria-label="Real2Sim Studio làm gì">
        <p className="text-sm font-medium tracking-wide text-ember-strong uppercase">Từ video tới scene mô phỏng</p>
        <ol className="space-y-5">
          {STEPS.map((step, index) => (
            <li key={step} className="flex items-start gap-3">
              <span className="grid size-7 shrink-0 place-items-center rounded-full border border-line-strong text-xs font-semibold text-ink-muted">
                {index + 1}
              </span>
              <span className="pt-1 text-[15px]">{step}</span>
            </li>
          ))}
        </ol>
        <p className="text-sm text-ink-muted">Editor tạo scene và chỉnh sửa; Reviewer duyệt và phát hành. Quyền do mã mời quyết định.</p>
      </aside>
    </main>
  );
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useAuth();
  const { fieldErrors, validate } = useFieldValidation();
  const ids = { email: useId(), password: useId() };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      await refresh();
      notifySuccess("Đã đăng nhập.");
      router.push(safeNext(params.get("next")));
    } catch (cause) {
      setError(errorMessage(cause, "Đăng nhập thất bại"));
      setBusy(false);
    }
  }

  return (
    <Shell title="Đăng nhập" lead="Dành cho thành viên nhóm. Khách vẫn có thể thử video mẫu mà không cần tài khoản.">
      <form onInvalid={validate} onBlurCapture={validate} onChangeCapture={validate} onSubmit={submit} className="space-y-4">
        <Field error={fieldErrors[ids.email]} id={ids.email} label="Email">
          <Input id={ids.email} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} />
        </Field>
        <Field error={fieldErrors[ids.password]} id={ids.password} label="Mật khẩu">
          <Input id={ids.password} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT} />
        </Field>
        {error && <Notice tone="rust">{error}</Notice>}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <LogIn aria-hidden />}
          Đăng nhập
        </Button>
        <p className="text-center text-sm text-ink-muted">
          Có mã mời?{" "}
          <Link href={"/register?next=" + encodeURIComponent(safeNext(params.get("next")))} className="font-medium text-ember-strong underline-offset-4 hover:underline">
            Tạo tài khoản
          </Link>
        </p>
      </form>
    </Shell>
  );
}

export function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useAuth();
  const { fieldErrors, validate } = useFieldValidation();
  const ids = { code: useId(), name: useId(), email: useId(), password: useId() };
  const [code, setCode] = useState(params.get("code") ?? "");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await register({ invite_code: code.trim(), email, display_name: name.trim(), password });
      await refresh();
      notifySuccess("Đã tạo tài khoản và đăng nhập.");
      router.push(safeNext(params.get("next")));
    } catch (cause) {
      setError(errorMessage(cause, "Không tạo được tài khoản"));
      setBusy(false);
    }
  }

  return (
    <Shell title="Tạo tài khoản" lead="Nhập mã mời do Reviewer của nhóm gửi. Mã chỉ dùng được một lần.">
      <form onInvalid={validate} onBlurCapture={validate} onChangeCapture={validate} onSubmit={submit} className="space-y-4">
        <Field error={fieldErrors[ids.code]} id={ids.code} label="Mã mời">
          <Input id={ids.code} required value={code} onChange={(e) => setCode(e.target.value)} className={INPUT} autoComplete="off" />
        </Field>
        <Field error={fieldErrors[ids.name]} id={ids.name} label="Tên hiển thị">
          <Input id={ids.name} required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} className={INPUT} autoComplete="name" />
        </Field>
        <Field error={fieldErrors[ids.email]} id={ids.email} label="Email">
          <Input id={ids.email} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} autoComplete="email" />
        </Field>
        <Field error={fieldErrors[ids.password]} id={ids.password} label="Mật khẩu (ít nhất 10 ký tự)">
          <Input id={ids.password} type="password" minLength={10} required value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT} autoComplete="new-password" />
        </Field>
        {error && <Notice tone="rust">{error}</Notice>}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <UserPlus aria-hidden />}
          Tạo tài khoản
        </Button>
        <p className="text-center text-sm text-ink-muted">Đã có tài khoản? <Link href={"/login?next=" + encodeURIComponent(safeNext(params.get("next")))} className="font-medium text-ember-strong hover:underline">Đăng nhập</Link></p>
      </form>
    </Shell>
  );
}
