"use client";
import { LogIn, LogOut, UserRound } from "lucide-react";
import { useState } from "react";
import { GuardedLink as Link, useNavigationGuard } from "@/features/shell/NavigationGuard";
import { useAuth } from "@/features/studio/AuthProvider";
import { GuestQuotaStatus } from "@/features/studio/auth/GuestQuotaStatus";
import { isTrialGuest } from "@/features/studio/auth/trialGuest";
import { PageHeader, ErrorFeedback, HelpDetails } from "@/components/studio/feedback";
import { Badge, Button, Card, EmptyState, buttonVariants } from "@/components/studio/primitives";
import { errorMessage } from "@/lib/ui-error";

export function AccountPage() {
  const { me, logout } = useAuth();
  const { navigate } = useNavigationGuard();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function signOut() {
    setBusy(true); setError(null);
    try { await logout(); } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <main className="mx-auto max-w-3xl space-y-6 px-4 py-8 sm:px-6">
    <PageHeader title="Tài khoản" description="Thông tin và quyền truy cập của phiên đăng nhập hiện tại." />
    {!me ? <p role="status">Đang đọc tài khoản…</p> : !me.auth_required ? <EmptyState icon={<UserRound aria-hidden />} title="Chế độ local — không có tài khoản">Bản cài đặt này không bật đăng nhập nên không có thông tin tài khoản.</EmptyState> : !me.user ? <EmptyState icon={<LogIn aria-hidden />} title="Đăng nhập để xem tài khoản" action={<Link href="/login?next=/account" className={buttonVariants({})}>Đăng nhập</Link>} /> : <>
      <Card className="p-5">
        <div className="flex items-center gap-3"><span className="grid size-12 place-items-center rounded-full bg-ember-soft text-xl font-semibold">{me.user.display_name.slice(0, 1).toUpperCase()}</span><div><h2 className="font-bold">{me.user.display_name}</h2><Badge tone="neutral">{me.user.role === "reviewer" ? "Reviewer" : me.user.role === "guest" ? "Guest" : "Editor"}</Badge></div></div>
        <dl className="mt-5 divide-y divide-line">
          {[["Email", me.user.email], ["Vai trò", me.user.role === "guest" ? "Guest" : me.user.role === "reviewer" ? "Reviewer" : "Editor"], ["Trạng thái", me.user.active ? "Đang hoạt động" : "Đã vô hiệu hoá"], ["Hạn mức xử lý", me.user.role === "reviewer" ? "Không giới hạn" : me.user.role === "guest" ? (me.quota ? `${me.quota.remaining}/${me.quota.limit} lượt còn lại hôm nay` : "Chưa xác minh") : String(me.user.daily_job_quota) + " lần / 24 giờ"]].map(([label, value]) => <div key={label} className="grid gap-1 py-3 sm:grid-cols-[12rem_1fr]"><dt className="text-sm text-ink-muted">{label}</dt><dd className="break-words text-sm">{value}</dd></div>)}
        </dl>
      </Card>
      {me.user.role === "guest" && <GuestQuotaStatus quota={me.quota} />}
      <HelpDetails title="Quyền của tài khoản">{me.user.role === "reviewer" ? "Reviewer làm được mọi việc của Editor, thêm quản lý nhóm và duyệt gói." : me.user.role === "guest" ? `Khách xem được mọi scene và chỉ sửa scene mình tạo. Mỗi ngày có tối đa 3 lượt tạo scene hoặc thử lại.${isTrialGuest(me.user.email) ? " Tài khoản dùng thử này gắn với trình duyệt hiện tại; xoá dữ liệu trình duyệt sẽ mất tài khoản." : ""}` : "Editor tải dữ liệu, tạo và chỉnh scene. Reviewer quyết định phát hành."}<p>Sửa vật thể sẽ tạo phiên bản scene mới; gói và kết quả duyệt cũ cần làm lại.</p></HelpDetails>
      {error && <ErrorFeedback message={error} />}
      <Button variant="secondary" disabled={busy} onClick={() => void navigate(() => { void signOut(); }, undefined, true)}><LogOut aria-hidden />{busy ? "Đang đăng xuất…" : "Đăng xuất"}</Button>
    </>}
  </main>;
}
