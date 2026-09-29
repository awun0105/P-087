"use client";

import { Loader2, LogIn, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState } from "react";

import { Button, Card, Notice } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { login, register } from "@/lib/api/auth";

const INPUT =
  "mt-1.5 h-10 w-full rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm outline-none focus-visible:border-ember focus-visible:ring-3 focus-visible:ring-ember/30";

/** Chỉ cho quay lại đường dẫn nội bộ (tránh open redirect qua `?next=`). */
export function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
    </div>
  );
}

function Shell({ title, lead, children }: { title: string; lead: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-md px-4 pt-14 pb-20 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-[15px] text-ink-muted">{lead}</p>
      <Card className="mt-8 p-6">{children}</Card>
    </main>
  );
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useAuth();
  const ids = { email: useId(), password: useId() };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      await refresh();
      router.push(safeNext(params.get("next")));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Đăng nhập thất bại");
      setBusy(false);
    }
  }

  return (
    <Shell title="Đăng nhập" lead="Dành cho thành viên nhóm. Khách vẫn có thể thử video mẫu mà không cần tài khoản.">
      <form onSubmit={submit} className="space-y-4">
        <Field id={ids.email} label="Email">
          <input id={ids.email} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} />
        </Field>
        <Field id={ids.password} label="Mật khẩu">
          <input id={ids.password} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT} />
        </Field>
        {error && <Notice tone="rust">{error}</Notice>}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <LogIn aria-hidden />}
          Đăng nhập
        </Button>
        <p className="text-center text-sm text-ink-muted">
          Có mã mời?{" "}
          <Link href="/register" className="font-medium text-ember-strong underline-offset-4 hover:underline">
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
  const ids = { code: useId(), name: useId(), email: useId(), password: useId() };
  const [code, setCode] = useState(params.get("code") ?? "");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register({ invite_code: code.trim(), email, display_name: name.trim(), password });
      await refresh();
      router.push("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không tạo được tài khoản");
      setBusy(false);
    }
  }

  return (
    <Shell title="Tạo tài khoản" lead="Nhập mã mời do Reviewer của nhóm gửi. Mã chỉ dùng được một lần.">
      <form onSubmit={submit} className="space-y-4">
        <Field id={ids.code} label="Mã mời">
          <input id={ids.code} required value={code} onChange={(e) => setCode(e.target.value)} className={INPUT} autoComplete="off" />
        </Field>
        <Field id={ids.name} label="Tên hiển thị">
          <input id={ids.name} required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} className={INPUT} autoComplete="name" />
        </Field>
        <Field id={ids.email} label="Email">
          <input id={ids.email} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} autoComplete="email" />
        </Field>
        <Field id={ids.password} label="Mật khẩu (ít nhất 10 ký tự)">
          <input id={ids.password} type="password" minLength={10} required value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT} autoComplete="new-password" />
        </Field>
        {error && <Notice tone="rust">{error}</Notice>}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <UserPlus aria-hidden />}
          Tạo tài khoản
        </Button>
      </form>
    </Shell>
  );
}
