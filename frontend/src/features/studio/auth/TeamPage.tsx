"use client";

import { Check, Copy, Loader2, Ticket, Users } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, EmptyState, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { createInvite, isReviewer, listUsers, updateUser, type PublicUser, type Role } from "@/lib/api/auth";

/** Quản lý nhóm cho Reviewer: phát mã mời, đổi role, khóa tài khoản, chỉnh hạn mức. */
export function TeamPage() {
  const { me } = useAuth();
  const [users, setUsers] = useState<PublicUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await listUsers();
    if (result.ok) {
      setUsers(result.data);
      setError(null);
    } else setError(result.error.detail);
  }, []);

  useEffect(() => {
    if (!me?.user || me.user.role !== "reviewer") return;
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [me, load]);

  if (me === null) {
    return (
      <main className="grid h-64 place-items-center" role="status">
        <Loader2 className="size-5 animate-spin text-ink-muted motion-reduce:animate-none" aria-hidden />
      </main>
    );
  }
  if (!me.auth_required || !me.user || !isReviewer(me)) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
        <EmptyState
          icon={<Users aria-hidden />}
          title={me.auth_required ? "Chỉ Reviewer quản lý nhóm" : "Deployment này chưa bật đăng nhập"}
          action={
            !me.user && me.auth_required ? (
              <Link href="/login?next=/team" className={buttonVariants({})}>
                Đăng nhập
              </Link>
            ) : undefined
          }
        >
          {me.auth_required ? "Đăng nhập bằng tài khoản Reviewer để mời thành viên." : "Đặt AUTH_REQUIRED=true để dùng tài khoản và phân quyền."}
        </EmptyState>
      </main>
    );
  }

  const self = me.user;
  async function change(user: PublicUser, changes: Partial<Pick<PublicUser, "role" | "active" | "daily_job_quota">>) {
    try {
      await updateUser(user.user_id, changes);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không cập nhật được");
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-4 pt-10 pb-20 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Nhóm</h1>
      <p className="mt-2 text-[15px] text-ink-muted">
        Editor dựng và chỉnh scene, có hạn mức số lần xử lý GPU (scene mới hoặc thử lại) mỗi 24 giờ do Reviewer chỉnh. Reviewer có
        thêm quyền duyệt scene, quản lý thành viên và không bị giới hạn.
      </p>
      <InviteCard />
      {error && (
        <Notice tone="rust" className="mt-6">
          {error}
        </Notice>
      )}
      <Card className="mt-6 overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-paper-sunken text-xs tracking-wide text-ink-subtle uppercase">
            <tr>
              <th className="px-4 py-3 font-medium">Thành viên</th>
              <th className="px-4 py-3 font-medium">Role</th>
              <th className="px-4 py-3 font-medium">Lượt GPU/24 giờ</th>
              <th className="px-4 py-3 font-medium">Trạng thái</th>
            </tr>
          </thead>
          <tbody>
            {(users ?? []).map((user) => {
              const isSelf = user.user_id === self.user_id;
              return (
                <tr key={user.user_id} className="border-t border-line">
                  <td className="px-4 py-3">
                    <p className="font-medium">
                      {user.display_name} {isSelf && <span className="text-ink-subtle">(bạn)</span>}
                    </p>
                    <p className="text-ink-muted">{user.email}</p>
                  </td>
                  <td className="px-4 py-3">
                    <select
                      aria-label={`Role của ${user.display_name}`}
                      value={user.role}
                      disabled={isSelf}
                      onChange={(event) => void change(user, { role: event.target.value as Role })}
                      className="h-9 rounded-lg border border-line-strong bg-paper-raised px-2"
                    >
                      <option value="editor">Editor</option>
                      <option value="reviewer">Reviewer</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    {user.role === "reviewer" ? (
                      <span className="text-ink-muted">Không giới hạn</span>
                    ) : (
                    <input
                      aria-label={`Hạn mức lượt xử lý GPU mỗi 24 giờ của ${user.display_name}`}
                      type="number"
                      min={0}
                      max={1000}
                      defaultValue={user.daily_job_quota}
                      onBlur={(event) => {
                        const value = Number(event.target.value);
                        if (Number.isInteger(value) && value !== user.daily_job_quota) void change(user, { daily_job_quota: value });
                      }}
                      className="h-9 w-20 rounded-lg border border-line-strong bg-paper-raised px-2 tabular-nums"
                    />
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {isSelf ? (
                      <Badge tone="sage">Đang hoạt động</Badge>
                    ) : (
                      <Button variant="ghost" size="sm" onClick={() => void change(user, { active: !user.active })}>
                        {user.active ? "Khóa" : "Mở khóa"}
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {users === null && !error && (
          <p className="flex items-center gap-2 p-4 text-sm text-ink-muted" role="status">
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
            Đang tải danh sách…
          </p>
        )}
      </Card>
    </main>
  );
}

function InviteCard() {
  const [role, setRole] = useState<Role>("editor");
  const [invite, setInvite] = useState<{ code: string; role: Role; expires_at: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setError(null);
    setCopied(false);
    try {
      setInvite(await createInvite(role));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không tạo được mã mời");
    }
  }

  const link = invite ? `${window.location.origin}/register?code=${encodeURIComponent(invite.code)}` : "";
  return (
    <Card className="mt-8 p-5 sm:p-6">
      <h2 className="flex items-center gap-2 text-base font-semibold">
        <Ticket className="size-4 text-ember-strong" aria-hidden />
        Mời thành viên
      </h2>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select
          aria-label="Role của mã mời"
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
          className="h-10 rounded-[10px] border border-line-strong bg-paper-raised px-3 text-sm"
        >
          <option value="editor">Editor — dựng và chỉnh scene</option>
          <option value="reviewer">Reviewer — thêm quyền duyệt</option>
        </select>
        <Button onClick={() => void generate()}>Tạo mã mời</Button>
      </div>
      {error && (
        <Notice tone="rust" className="mt-4">
          {error}
        </Notice>
      )}
      {invite && (
        <div className="mt-4 rounded-xl bg-paper-sunken p-4 text-sm">
          <p className="text-ink-muted">
            Gửi link này cho thành viên ({invite.role === "reviewer" ? "Reviewer" : "Editor"}). Mã chỉ hiện một lần, dùng
            được một lần, hết hạn {new Date(invite.expires_at).toLocaleDateString("vi-VN")}.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-lg bg-paper-raised px-3 py-2 font-mono text-xs">{link}</code>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(link).then(() => setCopied(true));
              }}
            >
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied ? "Đã chép" : "Sao chép"}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
