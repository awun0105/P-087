"use client";

import { errorMessage } from "@/lib/ui-error";

import { ArrowRight } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useCallback, useState } from "react";

import { Badge, Button, Card, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { sceneStatus } from "@/features/studio/sceneStatus";
import { usePolling } from "@/features/studio/usePolling";
import { canEdit } from "@/lib/api/auth";
import { listImports, listScenes } from "@/lib/api/studio";
import { STUDIO_ENTRY } from "@/lib/routes";
import type { ImportedScene, SceneSummary } from "@/lib/contracts/studio";

/** Trang đầu của app: việc đang chờ bạn và lối tạo scene. Danh sách đầy đủ nằm ở /scenes, cách bắt đầu ở /new. */
export function OverviewPage() {
  const { me } = useAuth();
  const signedIn = canEdit(me);
  return (
    <main className="mx-auto max-w-6xl space-y-8 px-4 pt-10 pb-20 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-extrabold tracking-tight">Tổng quan</h1>
          <p className="mt-2 text-[15px] leading-relaxed text-ink-muted">
            Xem việc đang làm và bắt đầu một scene mới. Bản xem 3D chưa phải scene sẵn sàng mô phỏng: còn phải xác nhận tỉ lệ, chọn vật thể và kiểm tra.
          </p>
        </div>
        {me !== null && (
          <div className="flex flex-wrap gap-2">
            {signedIn ? (
              <Link href="/new" className={buttonVariants({ size: "lg" })}>Tạo scene mới <ArrowRight aria-hidden /></Link>
            ) : (
              <Link href="/new/try-demo" className={buttonVariants({ size: "lg" })}>Thử với mẫu <ArrowRight aria-hidden /></Link>
            )}
            <Link href="/scenes" className={buttonVariants({ size: "lg", variant: "secondary" })}>Tất cả scene</Link>
          </div>
        )}
      </header>

      <section aria-labelledby="summary-heading">
        <h2 id="summary-heading" className="sr-only">Tổng hợp công việc</h2>
        {me === null ? <p role="status" className="text-sm text-ink-muted">Đang kiểm tra quyền truy cập…</p>
          : signedIn ? <WorkSummary key={me.user?.user_id ?? "local"} />
            : <Card className="p-5"><p className="font-medium">Đăng nhập để xem công việc của nhóm</p><p className="mt-2 text-sm leading-relaxed text-ink-muted">Chưa đăng nhập vẫn thử được bằng mẫu đã xử lý sẵn. Tải dữ liệu riêng và tạo scene cần tài khoản.</p><Link href={STUDIO_ENTRY} className="mt-3 inline-block text-sm font-medium text-ember-strong hover:underline">Đăng nhập</Link></Card>}
      </section>
    </main>
  );
}

interface Snapshot {
  scenes: SceneSummary[] | null;
  imports: ImportedScene[] | null;
  errors: string[];
}

/** Dữ liệu tổng hợp chỉ đọc API có sẵn; thiếu nguồn thì không hiển thị số 0 giả. */
function WorkSummary() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const load = useCallback(async (signal: AbortSignal) => {
    const [scenes, imports] = await Promise.all([listScenes(), listImports()]);
    if (signal.aborted) return;
    setSnapshot((previous) => ({
      scenes: scenes.ok ? scenes.data.scenes : previous?.scenes ?? null,
      imports: imports.ok ? imports.data.imports : previous?.imports ?? null,
      errors: [!scenes.ok && `Scenes: ${errorMessage(scenes.error)}`, !imports.ok && `Import: ${errorMessage(imports.error)}`].filter((value): value is string => Boolean(value)),
    }));
  }, []);
  usePolling(load, 20000, true);
  const scenes = snapshot?.scenes;
  const running = scenes?.filter((scene) => sceneStatus(scene.latest_job, scene.preview_ready, scene.awaiting_anonymization_review).group === "running").length;
  const waiting = scenes?.filter((scene) => ["action", "failed"].includes(sceneStatus(scene.latest_job, scene.preview_ready, scene.awaiting_anonymization_review).group)) ?? [];
  const stats = [
    { label: "Scene từ video", value: scenes?.length },
    { label: "Đang xử lý", value: running },
    { label: "Cần bạn xử lý", value: scenes ? waiting.length : undefined },
    { label: "Scene từ file 3DGS", value: snapshot?.imports?.length },
  ];
  return (
    <div className="space-y-4">
      {!snapshot && <p role="status" className="text-sm text-ink-muted">Đang tải tổng hợp…</p>}
      {snapshot && snapshot.errors.length > 0 && <Notice tone="rust">Chưa tải đủ dữ liệu tổng hợp. {snapshot.errors.join(" · ")} Dữ liệu đọc được trước đó được giữ lại. <Button variant="secondary" size="sm" className="ml-2" onClick={() => void load(new AbortController().signal)}>Thử lại</Button></Notice>}
      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((stat) => <div key={stat.label} className="rounded-2xl border border-line bg-paper-raised p-5"><dt className="text-ink-muted">{stat.label}</dt><dd className="mt-2 text-3xl font-bold value-tech">{stat.value === undefined ? "—" : stat.value}</dd></div>)}
      </dl>
      {scenes && scenes.length === 0 && <p className="text-sm text-ink-muted">Chưa có scene nào. Chọn “Tạo scene mới” để dựng từ video hoặc mở file 3DGS.</p>}
      {waiting.length > 0 && <Card className="p-5">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-bold">Scene đang chờ bạn</h3>
          <Link href="/scenes?filter=needs_action" className="text-sm font-medium text-ember-strong hover:underline">Xem tất cả</Link>
        </div>
        <ul className="mt-3 divide-y divide-line">{waiting.slice(0, 5).map((scene) => {
          const status = sceneStatus(scene.latest_job, scene.preview_ready, scene.awaiting_anonymization_review);
          return <li key={scene.project.project_id}><Link href={`/scenes/${encodeURIComponent(scene.latest_job!.job_id)}`} className="flex flex-wrap items-center justify-between gap-2 rounded py-3 focus-visible:outline-2 focus-visible:outline-ember"><span className="min-w-0 flex-1 truncate text-sm font-medium">{scene.project.name}</span><Badge tone={status.tone}>{status.label}</Badge><ArrowRight className="size-4 text-ember-strong" aria-hidden /></Link></li>;
        })}</ul>
      </Card>}
      {scenes && scenes.length > 0 && waiting.length === 0 && <p className="text-sm text-ink-muted">Không có scene nào đang chờ bạn.</p>}
    </div>
  );
}
