"use client";

import { ArrowRight, Clapperboard, Film, LogIn, Play, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";

import { Badge, Card, EmptyState, Notice, buttonVariants, formatBytes } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { sceneStatus } from "@/features/studio/sceneStatus";
import { usePolling } from "@/features/studio/usePolling";
import { canEdit } from "@/lib/api/auth";
import { listSamples, listScenes, sampleFileUrl } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { SampleSummary, SceneSummary } from "@/lib/contracts/studio";

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" });

/** Màn hình Scenes: video mẫu + danh sách scene của người dùng (dữ liệu từ backend). */
export function ScenesHome() {
  const [scenes, setScenes] = useState<SceneSummary[] | null>(null);
  const [samples, setSamples] = useState<SampleSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const { me } = useAuth();
  const signedIn = canEdit(me);

  const load = useCallback(async () => {
    // Khách không có quyền xem scene của nhóm: chỉ tải video mẫu, không poll lỗi 401.
    const [sceneResult, sampleResult] = await Promise.all([
      signedIn ? listScenes() : Promise.resolve(null),
      listSamples(),
    ]);
    if (sceneResult?.ok) {
      setScenes(sceneResult.data.scenes);
      setError(null);
    } else if (sceneResult) {
      setError(sceneResult.error.detail);
    }
    setSamples(sampleResult.ok ? sampleResult.data.samples : []);
  }, [signedIn]);

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

      {samples.length > 0 && <SamplesHero samples={samples} />}

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
        {me !== null && !signedIn && (
          <EmptyState
            icon={<LogIn aria-hidden />}
            title="Đăng nhập để xem scene của nhóm"
            action={
              <Link href="/login" className={buttonVariants({})}>
                Đăng nhập
              </Link>
            }
          >
            Khách có thể thử ngay với video mẫu ở trên.
          </EmptyState>
        )}
        {signedIn && scenes === null && !error && <SceneGridSkeleton />}
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
            Quay video bằng camera di chuyển chậm quanh khu vực cần dựng, rồi tải lên. Có thể thử trước với video mẫu.
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

/** Lối vào video mẫu: mở thẳng bước video mẫu trong trang Scene mới. */
function SamplesHero({ samples }: { samples: SampleSummary[] }) {
  return (
    <section aria-labelledby="samples-home-heading" className="mt-10">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="samples-home-heading" className="text-sm font-semibold tracking-wide text-ink-subtle uppercase">
          Thử với video mẫu
        </h2>
        <p className="text-sm text-ink-subtle">Đi qua đủ các bước như video của bạn; kết quả đã xử lý sẵn nên chạy nhanh.</p>
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {samples.map((sample) => (
          <li key={sample.sample_id}>
            <Link
              href={`/new?sample=${encodeURIComponent(sample.sample_id)}`}
              className="group flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-paper-raised transition-[border-color,box-shadow] duration-200 hover:border-line-strong hover:shadow-md focus-visible:ring-3 focus-visible:ring-ember/40 focus-visible:outline-none"
            >
              <div className="relative aspect-video bg-viewport">
                {sample.cover && (
                  // eslint-disable-next-line @next/next/no-img-element -- ảnh mẫu từ API, kích thước không cố định
                  <img src={sampleFileUrl(sample.sample_id, sample.cover)} alt="" className="size-full object-cover opacity-90" loading="lazy" />
                )}
                <Badge tone="ember" className="absolute top-3 left-3 bg-paper-raised/95">
                  <Clapperboard aria-hidden />
                  Video mẫu
                </Badge>
              </div>
              <div className="flex flex-1 items-center justify-between gap-3 p-4">
                <div className="min-w-0">
                  <p className="text-xs font-medium tracking-wide text-ink-subtle uppercase">
                    {sample.source.dataset} · {sample.source.sequence}
                  </p>
                  <p className="mt-1 truncate font-semibold text-ink">{sample.title}</p>
                </div>
                <Play className="size-4 shrink-0 text-ember-strong transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
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
