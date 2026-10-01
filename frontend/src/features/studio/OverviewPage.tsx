"use client";

import { errorMessage } from "@/lib/ui-error";

import { ArrowRight, Box, Clapperboard, Film, Layers3, ListChecks, ShieldCheck, Workflow } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useCallback, useState, type ReactNode } from "react";

import { Badge, Button, Card, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { sceneStatus } from "@/features/studio/sceneStatus";
import { usePolling } from "@/features/studio/usePolling";
import { canEdit } from "@/lib/api/auth";
import { listImports, listScenes } from "@/lib/api/studio";
import { STUDIO_ENTRY } from "@/lib/routes";
import type { ImportedScene, SceneSummary } from "@/lib/contracts/studio";

const JOURNEY = [
  { label: "Nhập dữ liệu", detail: "Video để dựng scene; PLY/ZIP để mở 3DGS đã có.", icon: Film },
  { label: "Dựng & theo dõi", detail: "Job xử lý video, publish bản xem và chờ xác nhận tỉ lệ mét.", icon: Workflow },
  { label: "Chuẩn bị scene", detail: "Xác nhận vật thể, chỉnh scene và tạo gói mô phỏng.", icon: Layers3 },
  { label: "Kiểm tra & xuất", detail: "Lấy đúng bản làm việc, candidate hoặc release của revision.", icon: ShieldCheck },
] as const;

/** Trang đầu giới thiệu và tổng hợp; danh sách cùng CTA tạo scene thuộc /scenes. */
export function OverviewPage() {
  const { me } = useAuth();
  const signedIn = canEdit(me);
  return (
    <main className="mx-auto max-w-6xl space-y-10 px-4 pt-10 pb-20 sm:px-6">
      <section className="relative overflow-hidden rounded-3xl border border-line bg-paper-raised p-6 sm:p-10" aria-labelledby="overview-title">
        <div aria-hidden className="pointer-events-none absolute -top-24 -right-20 size-80 rounded-full bg-ember-soft/60 blur-3xl" />
        <div className="relative max-w-3xl">
          <p className="text-xs font-semibold tracking-widest text-ember-strong uppercase">Real2Sim Studio</p>
          <h1 id="overview-title" className="mt-4 text-3xl leading-tight font-semibold tracking-tight sm:text-4xl">Từ dữ liệu thực đến scene 3D cho mô phỏng</h1>
          <p className="mt-4 max-w-2xl text-base leading-relaxed text-ink-muted">Một không gian để dựng scene từ video, xem 3DGS, chuẩn bị vật thể và theo dõi kết quả. Bắt đầu trong Scenes; mỗi scene giữ tiến trình, Studio, kiểm tra và file đầu ra của riêng nó.</p>
          <Link href="/scenes" className={`${buttonVariants({ size: "lg" })} mt-6`}>Mở Scenes <ArrowRight aria-hidden /></Link>
        </div>
      </section>

      <section aria-labelledby="summary-heading">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="summary-heading" className="text-xl font-semibold">Tổng hợp công việc</h2>
            <p className="mt-1 text-sm text-ink-muted">Scene và lần xử lý mới nhất, theo quyền truy cập của bạn.</p>
          </div>
          <Link href="/jobs" className="inline-flex items-center gap-1 text-sm font-medium text-ember-strong hover:underline">Xem Jobs <ArrowRight className="size-4" aria-hidden /></Link>
        </div>
        {me === null ? <p role="status" className="text-sm text-ink-muted">Đang kiểm tra quyền truy cập…</p>
          : signedIn ? <WorkSummary key={me.user?.user_id ?? "local"} />
            : <Card className="p-5"><p className="font-medium">Khám phá Studio với mẫu đã xử lý sẵn</p><p className="mt-2 text-sm leading-relaxed text-ink-muted">Mở Scenes để xem mẫu. Đăng nhập để xem công việc của nhóm, tải dữ liệu riêng và tạo scene.</p><Link href={STUDIO_ENTRY} className="mt-3 inline-block text-sm font-medium text-ember-strong hover:underline">Đăng nhập để xem tổng hợp</Link></Card>}
      </section>

      <section aria-labelledby="journey-heading">
        <h2 id="journey-heading" className="text-xl font-semibold">Một hành trình, bốn vùng công việc</h2>
        <p className="mt-1 text-sm text-ink-muted">Luồng dựng từ video đi từ dữ liệu tới scene và kết quả có thể kiểm tra.</p>
        <ol className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {JOURNEY.map((step, index) => <li key={step.label} className="rounded-2xl border border-line bg-paper-raised p-5">
            <div className="flex items-center justify-between"><step.icon className="size-5 text-ember-strong" aria-hidden /><span className="font-mono text-xs text-ink-subtle">0{index + 1}</span></div>
            <h3 className="mt-5 font-semibold">{step.label}</h3><p className="mt-2 text-sm leading-relaxed text-ink-muted">{step.detail}</p>
          </li>)}
        </ol>
        <p className="mt-3 text-sm leading-relaxed text-ink-muted">Validation Isaac và phát hành chỉ khả dụng khi có runtime, báo cáo và quyết định Reviewer hợp lệ. Bản xem 3DGS chưa phải scene đã được kiểm tra để mô phỏng.</p>
      </section>

      <section aria-labelledby="sources-heading">
        <h2 id="sources-heading" className="text-xl font-semibold">Chọn điểm bắt đầu phù hợp</h2>
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          <SourceInfo icon={<Film aria-hidden />} title="Dựng từ video" kind="MP4 / MOV">Video RGB tạo job tái dựng. Xác nhận tỉ lệ và chuẩn bị vật thể trước khi tạo gói mô phỏng.</SourceInfo>
          <SourceInfo icon={<Box aria-hidden />} title="Mở 3DGS có sẵn" kind="PLY / ZIP">Xem và chỉnh Gaussian, xuất PLY/SOG. Nhánh import không có pipeline hệ mét, collision hoặc review/release.</SourceInfo>
          <SourceInfo icon={<Clapperboard aria-hidden />} title="Khám phá bằng mẫu" kind="Đã xử lý sẵn">Xem replay và kết quả của mẫu có sẵn. Không tạo job reconstruction mới.</SourceInfo>
        </div>
      </section>

      <div className="grid gap-4 sm:grid-cols-2">
        <AreaLink href="/scenes" icon={<Clapperboard aria-hidden />} title="Scenes" detail="Thư viện scene, mẫu và file import. Tạo scene mới hoặc tiếp tục scene đang làm." />
        <AreaLink href="/jobs" icon={<ListChecks aria-hidden />} title="Jobs" detail="Theo dõi lần xử lý mới nhất của từng scene; mở scene để xem tiến trình và phục hồi lỗi." />
      </div>
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
  const running = scenes?.filter((scene) => sceneStatus(scene.latest_job, scene.preview_ready).group === "running").length;
  const action = scenes?.filter((scene) => sceneStatus(scene.latest_job, scene.preview_ready).group === "action").length;
  const continuing = scenes?.filter((scene) => ["running", "action", "failed"].includes(sceneStatus(scene.latest_job, scene.preview_ready).group)).slice(0, 3) ?? [];
  const stats = [
    { label: "Scene từ video", value: scenes?.length },
    { label: "Đang xử lý", value: running },
    { label: "Cần xác nhận tỉ lệ", value: action },
    { label: "Scene import", value: snapshot?.imports?.length },
  ];
  return (
    <div className="space-y-4">
      {!snapshot && <p role="status" className="text-sm text-ink-muted">Đang tải tổng hợp…</p>}
      {snapshot && snapshot.errors.length > 0 && <Notice tone="rust">Chưa tải đủ dữ liệu tổng hợp. {snapshot.errors.join(" · ")} Dữ liệu đọc được trước đó được giữ lại. <Button variant="secondary" size="sm" className="ml-2" onClick={() => void load(new AbortController().signal)}>Thử lại</Button></Notice>}
      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((stat) => <div key={stat.label} className="rounded-2xl border border-line bg-paper-raised p-5"><dt className="text-sm text-ink-muted">{stat.label}</dt><dd className="mt-2 text-3xl font-semibold tabular-nums">{stat.value === undefined ? "—" : stat.value}</dd></div>)}
      </dl>
      {scenes && scenes.length === 0 && <p className="text-sm text-ink-muted">Chưa có scene từ video. Vào Scenes để chọn mẫu, mở 3DGS hoặc tạo scene đầu tiên.</p>}
      {continuing.length > 0 && <Card className="p-5">
        <h3 className="font-semibold">Công việc cần tiếp tục</h3>
        <ul className="mt-3 divide-y divide-line">{continuing.map((scene) => {
          const status = sceneStatus(scene.latest_job, scene.preview_ready);
          return <li key={scene.project.project_id}><Link href={`/scenes/${encodeURIComponent(scene.latest_job!.job_id)}`} className="flex flex-wrap items-center justify-between gap-2 rounded py-3 focus-visible:outline-2 focus-visible:outline-ember"><span className="min-w-0 flex-1 truncate text-sm font-medium">{scene.project.name}</span><Badge tone={status.tone}>{status.label}</Badge><ArrowRight className="size-4 text-ember-strong" aria-hidden /></Link></li>;
        })}</ul>
      </Card>}
    </div>
  );
}

function SourceInfo({ icon, title, kind, children }: { icon: ReactNode; title: string; kind: string; children: ReactNode }) {
  return <Card className="p-5"><div className="flex items-center justify-between gap-3"><span className="grid size-10 place-items-center rounded-xl bg-ember-soft text-ember-strong [&_svg]:size-5">{icon}</span><Badge tone="neutral">{kind}</Badge></div><h3 className="mt-4 font-semibold">{title}</h3><p className="mt-2 text-sm leading-relaxed text-ink-muted">{children}</p></Card>;
}

function AreaLink({ href, icon, title, detail }: { href: string; icon: ReactNode; title: string; detail: string }) {
  return <Link href={href} className="flex items-start gap-4 rounded-2xl border border-line bg-paper-raised p-5 transition-colors hover:border-ember focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember"><span className="mt-1 text-ember-strong [&_svg]:size-5">{icon}</span><span className="flex-1"><span className="block font-semibold">{title}</span><span className="mt-1 block text-sm leading-relaxed text-ink-muted">{detail}</span></span><ArrowRight className="mt-1 size-4 text-ink-muted" aria-hidden /></Link>;
}
