"use client";

import { errorMessage } from "@/lib/ui-error";

import { ArrowRight, Clapperboard, Film, LayoutGrid, List, LogIn, Play, Plus, RefreshCw, Search } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useCallback, useMemo, useState } from "react";

import { Input } from "@/components/shadcn/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/shadcn/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/shadcn/toggle-group";
import { Badge, Card, EmptyState, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { STATUS_FILTERS, sceneStatus, type SceneStatusGroup } from "@/features/studio/sceneStatus";
import { usePolling } from "@/features/studio/usePolling";
import { canEdit } from "@/lib/api/auth";
import { listImports, listSamples, listScenes, sampleFileUrl } from "@/lib/api/studio";
import { cn } from "@/lib/cn";
import type { ImportedScene, SampleSummary, SceneSummary } from "@/lib/contracts/studio";
import { useListState, pageSlice, ListPagination, SortControl } from "@/features/studio/ListControls";
import { formatBytes } from "@/lib/format";

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" });

/** Màn hình Scenes: video mẫu + danh sách scene của người dùng (dữ liệu từ backend). */
export function ScenesHome() {
  const [scenes, setScenes] = useState<SceneSummary[] | null>(null);
  const [imports, setImports] = useState<ImportedScene[]>([]);
  const [samples, setSamples] = useState<SampleSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const { me } = useAuth();
  const signedIn = canEdit(me);

  const load = useCallback(async () => {
    // Khách không có quyền xem scene của nhóm: chỉ tải video mẫu, không poll lỗi 401.
    const [sceneResult, sampleResult, importResult] = await Promise.all([
      signedIn ? listScenes() : Promise.resolve(null),
      listSamples(),
      signedIn ? listImports() : Promise.resolve(null),
    ]);
    if (importResult?.ok) { setImports(importResult.data.imports); setImportError(null); }
    else if (importResult) setImportError(errorMessage(importResult.error));
    if (sceneResult?.ok) {
      setScenes(sceneResult.data.scenes);
      setError(null);
    } else if (sceneResult) {
      setError(errorMessage(sceneResult.error));
    }
    if (sampleResult.ok) { setSamples(sampleResult.data.samples); setSampleError(null); }
    else setSampleError(errorMessage(sampleResult.error));
  }, [signedIn]);

  const { query, setQuery, filter, setFilter, view, setView, sort, setSort, params, update, clear } = useListState();
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (scenes ?? []).filter(
      (scene) =>
        (!needle || scene.project.name.toLowerCase().includes(needle)) &&
        (filter === "all" || sceneStatus(scene.latest_job, scene.preview_ready).group === filter),
    ).sort((a, b) => sort === "name" ? a.project.name.localeCompare(b.project.name, "vi") : Date.parse(b.project.created_at ?? b.latest_job?.started_at ?? "") - Date.parse(a.project.created_at ?? a.latest_job?.started_at ?? ""));
  }, [scenes, query, filter, sort]);

  const pagination = pageSlice(shown, params.get("page"), 12);
  const filteredImports = imports.filter((item) => item.name.toLowerCase().includes(query.trim().toLowerCase())).sort((a, b) => sort === "name" ? a.name.localeCompare(b.name, "vi") : Date.parse(b.created_at) - Date.parse(a.created_at));
  const importPage = pageSlice(filteredImports, params.get("importsPage"), 12);
  const filteredSamples = samples.filter((item) => item.title.toLowerCase().includes(query.trim().toLowerCase()));
  const samplePage = pageSlice(filteredSamples, params.get("samplesPage"), 12);
  const anyActive = scenes?.some((scene) => sceneStatus(scene.latest_job, scene.preview_ready).active) ?? true;
  usePolling(load, signedIn && anyActive ? 4000 : 20000, true);
  const continuing = (scenes ?? []).filter((scene) => {
    const group = sceneStatus(scene.latest_job, scene.preview_ready).group;
    return group === "action" || group === "running" || group === "failed";
  }).slice(0, 3);

  return (
    <main className="mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-ink">Scenes</h1>
          <p className="mt-1.5 max-w-xl text-[15px] leading-relaxed text-ink-muted">
            Tiếp tục scene đang làm, dựng từ video hoặc mở một file 3DGS đã có.
          </p>
        </div>
        <Link href="/new" className={buttonVariants({ size: "lg" })}><Plus aria-hidden /> Scene mới</Link>
      </div>

      {!signedIn && samples.length > 0 && <SamplesHero samples={samplePage.items} />}
      {!signedIn && sampleError && <Notice tone="rust" className="mt-6">Không tải được mẫu: {sampleError}. Trang sẽ thử lại.</Notice>}

      {signedIn && continuing.length > 0 && (
        <section aria-labelledby="continue-heading" className="mt-8 rounded-2xl border border-line bg-paper-raised p-5">
          <div className="flex items-center justify-between gap-2">
            <h2 id="continue-heading" className="font-bold">Tiếp tục công việc</h2>
            <Link href="/jobs" className="text-sm font-medium text-ember-strong hover:underline">Xem Jobs</Link>
          </div>
          <ul className="mt-3 divide-y divide-line">
            {continuing.map((scene) => {
              const status = sceneStatus(scene.latest_job, scene.preview_ready);
              return <li key={scene.project.project_id}>
                <Link href={`/scenes/${encodeURIComponent(scene.latest_job!.job_id)}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg py-3 focus-visible:outline-2 focus-visible:outline-ember">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{scene.project.name}</span>
                  <Badge tone={status.tone}>{status.label}</Badge>
                  <ArrowRight className="size-4 text-ember-strong" aria-hidden />
                </Link>
              </li>;
            })}
          </ul>
        </section>
      )}

      <section aria-labelledby="scenes-heading" className="mt-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="scenes-heading" className="label-tech text-ink-muted">
            Scene từ video · job
          </h2>
          {signedIn && scenes && scenes.length > 0 && (
            <span className="text-sm text-ink-subtle">{scenes.length} scene</span>
          )}
        </div>
        {signedIn && error && (
          <Notice tone="rust" icon={<RefreshCw aria-hidden />} className="mb-4">
            Không tải được danh sách scene: {error}. Trang sẽ tự thử lại.
          </Notice>
        )}
        {me !== null && !signedIn && (
          <EmptyState
            icon={<LogIn aria-hidden />}
            title="Đăng nhập để xem scene của nhóm"
            action={
              <Link href="/login?next=/scenes" className={buttonVariants({})}>
                Đăng nhập
              </Link>
            }
          >
            Khách có thể thử với mẫu đã xử lý sẵn.
          </EmptyState>
        )}
        {me === null && <p role="status" className="text-sm text-ink-muted">Đang kiểm tra quyền truy cập…</p>}
        {signedIn && scenes === null && !error && <SceneGridSkeleton />}
        {signedIn && scenes && scenes.length === 0 && (
          <EmptyState
            icon={<Film aria-hidden />}
            title="Chưa có scene nào"
          >
            Chọn “Scene mới” ở đầu trang để dựng từ video hoặc mở file 3DGS. Bạn cũng có thể thử mẫu đã xử lý sẵn.
          </EmptyState>
        )}
        {signedIn && (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="relative min-w-48 flex-1 sm:max-w-xs">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Tìm theo tên scene"
                aria-label="Tìm theo tên scene"
                className="pl-8"
              />
            </div>
            <ToggleGroup
              type="single"
              value={filter}
              onValueChange={(value) => value && setFilter(value as SceneStatusGroup | "all")}
              variant="outline"
              size="sm"
              aria-label="Lọc theo trạng thái"
            >
              {STATUS_FILTERS.map((item) => (
                <ToggleGroupItem key={item.value} value={item.value}>
                  {item.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <SortControl value={sort} onChange={setSort} />
            <ToggleGroup
              type="single"
              value={view}
              onValueChange={(value) => {
                if (!value) return;
                setView(value as "grid" | "list");
              }}
              variant="outline"
              size="sm"
              className="ml-auto"
              aria-label="Kiểu hiển thị"
            >
              <ToggleGroupItem value="grid" aria-label="Lưới">
                <LayoutGrid aria-hidden />
              </ToggleGroupItem>
              <ToggleGroupItem value="list" aria-label="Danh sách">
                <List aria-hidden />
              </ToggleGroupItem>
            </ToggleGroup>
          </div>
        )}
        {signedIn && scenes && scenes.length > 0 && shown.length === 0 && (
          <p className="rounded-xl border border-line p-6 text-center text-sm text-ink-muted">
            Không có scene khớp bộ lọc.{" "}
            <button type="button" className="font-medium text-ember-strong hover:underline" onClick={clear}>
              Xoá bộ lọc
            </button>
          </p>
        )}
        {signedIn && shown.length > 0 && view === "grid" && (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pagination.items.map((scene) => (
              <li key={scene.project.project_id}>
                <SceneCard scene={scene} />
              </li>
            ))}
          </ul>
        )}
        {signedIn && shown.length > 0 && view === "list" && <SceneTable scenes={pagination.items} />}
        {signedIn && <ListPagination {...pagination} total={shown.length} onChange={(page) => update({ page: String(page) })} />}
      </section>

      {signedIn && importError && <Notice tone="rust" className="mt-6">Không tải được scene import: {importError}. Trang sẽ thử lại.</Notice>}
      {signedIn && imports.length > 0 && (
        <section aria-labelledby="imports-heading" className="mt-10">
          <h2 id="imports-heading" className="label-tech mb-4 text-ink-muted">
            Scene import · chỉ xem/chỉnh Gaussian
          </h2>
          <ul className={view === "list" ? "space-y-2" : "grid gap-3 sm:grid-cols-2 lg:grid-cols-3"}>
            {importPage.items.map((item) => (
              <li key={item.import_id}>
                <Link
                  href={`/imports/${item.import_id}`}
                  className="flex items-center justify-between gap-3 rounded-xl border border-line bg-paper-raised p-4 text-sm transition-colors hover:border-line-strong"
                >
                  <span className="truncate font-medium text-ink">{item.name}</span>
                  <span className="shrink-0 text-xs text-ink-subtle">
                    {item.status === "READY" ? "Mở xem/chỉnh" : item.status === "FAILED" ? "Lỗi" : "Đang nén…"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <ListPagination {...importPage} total={filteredImports.length} onChange={(page) => update({ importsPage: String(page) })} />
          {filteredImports.length === 0 && <p className="text-sm text-ink-muted">Không có scene import khớp tên tìm kiếm.</p>}
        </section>
      )}
      {signedIn && samples.length > 0 && <SamplesHero samples={samplePage.items} />}
      {samples.length > 0 && filteredSamples.length === 0 && <p className="mt-4 text-sm text-ink-muted">Không có mẫu khớp tìm kiếm.</p>}
      {samples.length > 0 && <ListPagination {...samplePage} total={filteredSamples.length} onChange={(page) => update({ samplesPage: String(page) })} />}
      {signedIn && sampleError && <Notice tone="rust" className="mt-6">Không tải được mẫu: {sampleError}. Trang sẽ thử lại.</Notice>}
    </main>
  );
}

/** Lối vào video mẫu: mở thẳng bước video mẫu trong trang Scene mới. */
function SamplesHero({ samples }: { samples: SampleSummary[] }) {
  return (
    <section aria-labelledby="samples-home-heading" className="mt-10">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="samples-home-heading" className="label-tech text-ink-muted">
          Thử với video mẫu
        </h2>
        <p className="text-sm text-ink-subtle">Kết quả đã xử lý sẵn · phát lại để khám phá · không tạo job mới.</p>
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
                  <img src={sampleFileUrl(sample.sample_id, sample.cover)} alt="" className="size-full object-cover opacity-90" loading="lazy" decoding="async" />
                )}
                <Badge tone="ember" className="absolute top-3 left-3 bg-paper-raised/95">
                  <Clapperboard aria-hidden />
                  Video mẫu
                </Badge>
              </div>
              <div className="flex flex-1 items-center justify-between gap-3 p-4">
                <div className="min-w-0">
                  <p className="label-tech text-ink-muted">
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
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  const status = sceneStatus(scene.latest_job, scene.preview_ready);
  const job = scene.latest_job;
  const created = scene.project.created_at ? DATE.format(new Date(scene.project.created_at)) : null;
  // Frame đầu chỉ có sau khi trích frame; trước đó (hoặc ảnh lỗi) giữ icon.
  const hasFrames = job?.stage_artifacts.some((stage) => stage.stage_id === "ST-FRAME-EXTRACT") ?? false;
  const content = (
    <Card
      className={cn(
        "group flex h-full flex-col overflow-hidden transition-[border-color,box-shadow] duration-200",
        job && "hover:border-line-strong hover:shadow-md",
      )}
    >
      <div className="relative aspect-video w-full bg-paper-sunken">
        {job && hasFrames && !thumbnailFailed ? (
          // eslint-disable-next-line @next/next/no-img-element -- JPEG nhỏ do API tạo, không qua next/image
          <img
            src={`/api/v1/jobs/${encodeURIComponent(job.job_id)}/thumbnail.jpg`}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setThumbnailFailed(true)}
            className="size-full object-cover"
          />
        ) : (
          <div className="grid size-full place-items-center text-ink-subtle">
            <Film className="size-8" aria-hidden />
          </div>
        )}
        <Badge tone={status.tone} className="absolute top-3 right-3 shadow-sm">
          {status.active && <span className="studio-pulse size-1.5 rounded-full bg-current" aria-hidden />}
          {status.label}
        </Badge>
      </div>
      <div className="flex flex-1 flex-col p-5">
        <h3 className="truncate text-base font-bold text-ink">{scene.project.name}</h3>
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
/** Dạng danh sách: đọc nhanh trạng thái và mốc thời gian của nhiều scene. */
function SceneTable({ scenes }: { scenes: SceneSummary[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Scene</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="hidden md:table-cell">Video</TableHead>
            <TableHead className="hidden sm:table-cell">Tạo lúc</TableHead>
            <TableHead className="w-0" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {scenes.map((scene) => {
            const status = sceneStatus(scene.latest_job, scene.preview_ready);
            const job = scene.latest_job;
            return (
              <TableRow key={scene.project.project_id}>
                <TableCell className="max-w-64 truncate font-medium">{scene.project.name}</TableCell>
                <TableCell>
                  <Badge tone={status.tone}>{status.label}</Badge>
                </TableCell>
                <TableCell className="hidden max-w-56 truncate text-ink-muted md:table-cell">
                  {scene.project.input_video?.original_name ?? "—"}
                </TableCell>
                <TableCell className="hidden text-ink-muted sm:table-cell">
                  {scene.project.created_at ? DATE.format(new Date(scene.project.created_at)) : "—"}
                </TableCell>
                <TableCell className="text-right">
                  {job && (
                    <Link href={`/scenes/${encodeURIComponent(job.job_id)}`} className="font-medium whitespace-nowrap text-ember-strong hover:underline">
                      {scene.preview_ready ? "Mở scene" : "Xem tiến trình"}
                    </Link>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function SceneGridSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Đang tải scene">
      {[0, 1, 2].map((key) => (
        <div key={key} className="h-72 animate-pulse rounded-2xl border border-line bg-paper-raised motion-reduce:animate-none" />
      ))}
    </div>
  );
}
