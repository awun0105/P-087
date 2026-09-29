"use client";

import { ArrowRight, Clapperboard, Film, Play, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";

import { Badge, Card, EmptyState, Notice, buttonVariants, formatBytes } from "@/components/studio/primitives";
import { sceneStatus } from "@/features/studio/sceneStatus";
import { usePolling } from "@/features/studio/usePolling";
import { demoFileUrl, getDemo, listScenes } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { DemoManifest, SceneSummary } from "@/lib/contracts/studio";

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" });

/** Màn hình Scenes: kịch bản demo + danh sách scene của người dùng (dữ liệu từ backend). */
export function ScenesHome() {
  const [scenes, setScenes] = useState<SceneSummary[] | null>(null);
  const [demo, setDemo] = useState<DemoManifest | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [sceneResult, demoResult] = await Promise.all([listScenes(), getDemo()]);
    if (sceneResult.ok) {
      setScenes(sceneResult.data.scenes);
      setError(null);
    } else {
      setError(sceneResult.error.detail);
    }
    setDemo(demoResult.ok ? demoResult.data : null);
  }, []);

  const anyActive = scenes?.some((scene) => sceneStatus(scene.latest_job, scene.preview_ready).active) ?? true;
  usePolling(load, anyActive ? 4000 : 20000, true);

  return (
    <main className="mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink">Scenes</h1>
          <p className="mt-1.5 max-w-xl text-[15px] leading-relaxed text-ink-muted">
            Biến video quay trong kho thành scene 3D Gaussian Splatting để xem, chỉnh sửa và xuất file.
          </p>
        </div>
        <Link href="/new" className={buttonVariants({ size: "lg" })}>
          <Upload aria-hidden />
          Tải video lên
        </Link>
      </div>

      {demo && <DemoHero demo={demo} />}

      <section aria-labelledby="scenes-heading" className="mt-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="scenes-heading" className="text-sm font-semibold tracking-wide text-ink-subtle uppercase">
            Scene của bạn
          </h2>
          {scenes && scenes.length > 0 && (
            <span className="text-sm text-ink-subtle">{scenes.length} scene</span>
          )}
        </div>
        {error && (
          <Notice tone="rust" icon={<RefreshCw aria-hidden />} className="mb-4">
            Không tải được danh sách scene: {error}. Trang sẽ tự thử lại.
          </Notice>
        )}
        {scenes === null && !error && <SceneGridSkeleton />}
        {scenes && scenes.length === 0 && (
          <EmptyState
            icon={<Film aria-hidden />}
            title="Chưa có scene nào"
            action={
              <Link href="/new" className={buttonVariants({})}>
                <Upload aria-hidden />
                Tải video đầu tiên
              </Link>
            }
          >
            Quay video bằng camera di chuyển chậm quanh khu vực cần dựng, rồi tải lên. Có thể xem thử kịch bản demo trước.
          </EmptyState>
        )}
        {scenes && scenes.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {scenes.map((scene) => (
              <li key={scene.project.project_id}>
                <SceneCard scene={scene} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function DemoHero({ demo }: { demo: DemoManifest }) {
  const cover = demo.frames[Math.floor(demo.frames.length / 2)];
  return (
    <Card className="mt-10 overflow-hidden">
      <div className="grid md:grid-cols-[1.15fr_1fr]">
        <div className="relative min-h-56 bg-viewport">
          {cover && (
            // eslint-disable-next-line @next/next/no-img-element -- ảnh từ API demo, kích thước không cố định
            <img src={demoFileUrl(cover.name)} alt="" className="absolute inset-0 size-full object-cover opacity-90" />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-viewport/70 to-transparent" />
          <Badge tone="ember" className="absolute top-4 left-4 bg-paper-raised/95">
            <Clapperboard aria-hidden />
            Kịch bản demo
          </Badge>
        </div>
        <div className="flex flex-col justify-center gap-4 p-6 sm:p-8">
          <div>
            <p className="text-xs font-medium tracking-wide text-ink-subtle uppercase">
              {demo.source.dataset} · {demo.source.sequence}
            </p>
            <h2 className="mt-1.5 text-xl font-semibold tracking-tight">{demo.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-muted">{demo.description}</p>
          </div>
          <p className="text-sm leading-relaxed text-ink-muted">
            Đi qua đủ các bước như khi bạn tự tải video: tải lên, chọn video, theo dõi từng giai đoạn và mở scene 3D. Kết
            quả đã được xử lý sẵn nên tiến trình chạy nhanh.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Link href="/demo" className={buttonVariants({})}>
              <Play aria-hidden />
              Bắt đầu demo
            </Link>
            {demo.origin === "smoke_run" && <Badge tone="ochre">Bản smoke tạm</Badge>}
          </div>
        </div>
      </div>
    </Card>
  );
}

function SceneCard({ scene }: { scene: SceneSummary }) {
  const status = sceneStatus(scene.latest_job, scene.preview_ready);
  const job = scene.latest_job;
  const created = scene.project.created_at ? DATE.format(new Date(scene.project.created_at)) : null;
  const content = (
    <Card
      className={cn(
        "group flex h-full flex-col p-5 transition-[border-color,box-shadow] duration-200",
        job && "hover:border-line-strong hover:shadow-md",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="grid size-10 place-items-center rounded-xl bg-paper-sunken text-ink-muted">
          <Film className="size-5" aria-hidden />
        </div>
        <Badge tone={status.tone}>
          {status.active && <span className="studio-pulse size-1.5 rounded-full bg-current" aria-hidden />}
          {status.label}
        </Badge>
      </div>
      <h3 className="mt-4 truncate text-base font-semibold text-ink">{scene.project.name}</h3>
      <p className="mt-1 truncate text-sm text-ink-muted">
        {scene.project.input_video
          ? `${scene.project.input_video.original_name} · ${formatBytes(scene.project.input_video.size_bytes)}`
          : "Không có video"}
      </p>
      <div className="mt-auto flex items-center justify-between pt-5 text-xs text-ink-subtle">
        <span>{created}</span>
        {job && (
          <span className="flex items-center gap-1 font-medium text-ink-muted transition-colors group-hover:text-ember-strong">
            {scene.preview_ready ? "Mở scene" : "Xem tiến trình"}
            <ArrowRight className="size-3.5" aria-hidden />
          </span>
        )}
      </div>
    </Card>
  );
  if (!job) return content;
  return (
    <Link
      href={`/scenes/${encodeURIComponent(job.job_id)}`}
      className="block h-full rounded-2xl focus-visible:ring-3 focus-visible:ring-ember/40 focus-visible:outline-none"
    >
      {content}
    </Link>
  );
}

function SceneGridSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Đang tải scene">
      {[0, 1, 2].map((key) => (
        <div key={key} className="h-44 animate-pulse rounded-2xl border border-line bg-paper-raised motion-reduce:animate-none" />
      ))}
    </div>
  );
}
