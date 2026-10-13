"use client";

import { errorMessage } from "@/lib/ui-error";
import { ArrowRight, Film, LayoutGrid, List, LogIn, RefreshCw, Search } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useCallback, useMemo, useState } from "react";

import { Input } from "@/components/shadcn/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/shadcn/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/shadcn/toggle-group";
import { Badge, Card, EmptyState, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { STATUS_FILTERS, sceneSummaryStatus, type SceneStatusGroup } from "@/features/studio/sceneStatus";
import { usePolling } from "@/features/studio/usePolling";
import { canEdit, resourceCapabilityAllowed, type Me } from "@/lib/api/auth";
import { listScenes, moveSceneToTrash } from "@/lib/api/studio";
import { MoveToTrashButton } from "@/features/studio/trash/MoveToTrashButton";
import { cn } from "@/lib/cn";
import type { Actor, SceneSummary } from "@/lib/contracts/studio";
import { useListState, pageSlice, ListPagination, SortControl } from "@/features/studio/ListControls";
import { formatBytes, formatDuration } from "@/lib/format";
import { stageMeta } from "@/features/studio/stages";
import { progressHref } from "@/features/studio/inspection";

const DATE = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" });

const ROLE_LABELS: Record<string, string> = { editor: "Editor", reviewer: "Reviewer", guest: "Guest" };

function ActorAttribution({
  label,
  name,
  role,
}: {
  label: string;
  name: string;
  role?: string | null;
}) {
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-1 text-xs">
      <span className="text-ink-subtle">{label}: </span>
      <Badge tone="neutral" className="max-w-36 truncate normal-case">{name}</Badge>
      {" "}
      <Badge tone={role ? "neutral" : "ochre"}>
        {role ? ROLE_LABELS[role] ?? "Vai trò chưa xác định" : "Vai trò chưa xác định"}
      </Badge>
    </span>
  );
}

function actorAttribution(label: string, actor: Actor) {
  return <ActorAttribution key={`${label}-${actor.user_id}`} label={label} name={actor.display_name} role={actor.role} />;
}

/**
 * Thời gian xử lý = thời gian máy thật sự chạy các bước (backend cộng từ số đo của từng bước),
 * không gồm lúc xếp hàng và lúc chờ người dùng thao tác.
 */
function processingTime(scene: SceneSummary): string {
  const seconds = scene.processing_seconds;
  const finished = scene.latest_job?.completed_at != null;
  if (seconds == null) return finished ? "Chưa đo" : "—";
  return formatDuration(seconds) + (finished ? "" : " (chưa xong)");
}

/** Màn hình Scenes: danh sách scene của người dùng (dữ liệu từ backend). Video mẫu nằm ở `/new/try-demo`. */
export function ScenesHome() {
  const [scenes, setScenes] = useState<SceneSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { me } = useAuth();
  const signedIn = canEdit(me);

  const load = useCallback(async () => {
    // Khách không có quyền xem scene của nhóm: không gọi API, không poll lỗi 401.
    const sceneResult = signedIn ? await listScenes() : null;
    if (sceneResult?.ok) {
      setScenes(sceneResult.data.scenes);
      setError(null);
    } else if (sceneResult) {
      setError(errorMessage(sceneResult.error));
    }
  }, [signedIn]);

  const { query, setQuery, filter, setFilter, view, setView, sort, setSort, params, update, clear } = useListState();
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (scenes ?? []).filter(
      (scene) => {
        const group = sceneSummaryStatus(scene).group;
        return (!needle || scene.project.name.toLowerCase().includes(needle)) &&
               (filter === "all" || group === filter || (filter === "needs_action" && (group === "action" || group === "failed")));
      }
    ).sort((a, b) => sort === "name" ? a.project.name.localeCompare(b.project.name, "vi") : Date.parse(b.project.created_at ?? b.latest_job?.started_at ?? "") - Date.parse(a.project.created_at ?? a.latest_job?.started_at ?? ""));
  }, [scenes, query, filter, sort]);

  const pagination = pageSlice(shown, params.get("page"), 12);
  const anyActive = scenes?.some((scene) => sceneSummaryStatus(scene).active) ?? true;
  usePolling(load, signedIn && anyActive ? 4000 : 20000, true);

  return (
    <main className="mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-ink">Scenes từ video</h1>
          <p className="mt-1.5 max-w-xl text-[15px] leading-relaxed text-ink-muted">
            Tiếp tục scene đang làm, dựng từ video hoặc xem lại lịch sử reconstruction. Để mở file 3DGS trực tiếp, xem mục{" "}
            <Link href="/imports" className="font-medium text-ember-strong hover:underline">Scenes đã import</Link>.
          </p>
        </div>
      </div>

      {!signedIn && me !== null && (
        <Notice className="mt-8">
            Scene của nhóm chỉ hiện sau khi đăng nhập. Người xem chưa đăng nhập vẫn có thể mở kết quả mẫu ở{" "}
          <Link href="/new/try-demo" className="font-medium text-ember-strong hover:underline">Thử mẫu</Link>.
        </Notice>
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
            Người xem chưa đăng nhập có thể thử với mẫu đã xử lý sẵn.
          </EmptyState>
        )}
        {me === null && <p role="status" className="text-sm text-ink-muted">Đang kiểm tra quyền truy cập…</p>}
        {signedIn && scenes === null && !error && <SceneGridSkeleton />}
        {signedIn && scenes && scenes.length === 0 && (
          <EmptyState
            icon={<Film aria-hidden />}
            title="Chưa có scene nào"
          >
            Chọn “Tạo scene mới” từ thanh điều hướng để dựng từ video hoặc mở file 3DGS. Bạn cũng có thể thử mẫu đã xử lý sẵn.
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
              onValueChange={(value) => value && setFilter(value as SceneStatusGroup | "all" | "needs_action")}
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
          <ul className="grid auto-rows-fr gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pagination.items.map((scene) => (
              <li key={scene.project.project_id} className="relative min-w-0">
                <SceneCard scene={scene} />
                {/* Nằm ngoài thẻ link của card: nút trong link là HTML không hợp lệ và bấm sẽ điều hướng. */}
                {resourceCapabilityAllowed(me, scene.capabilities?.can_delete_project) && (
                  <MoveToTrashButton
                    name={scene.project.name}
                    move={() => moveSceneToTrash(scene.project.project_id)}
                    onMoved={() => void load()}
                    className="absolute top-3 left-3 shadow-sm"
                  />
                )}
              </li>
            ))}
          </ul>
        )}
        {signedIn && shown.length > 0 && view === "list" && <SceneTable scenes={pagination.items} me={me} onChanged={() => void load()} />}
        {signedIn && <ListPagination {...pagination} total={shown.length} onChange={(page) => update({ page: String(page) })} />}
      </section>
    </main>
  );
}

function SceneCard({ scene }: { scene: SceneSummary }) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  const status = sceneSummaryStatus(scene);
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
      <div className="relative aspect-video w-full shrink-0 overflow-hidden bg-paper-sunken">
        {job && hasFrames && !thumbnailFailed ? (
          // eslint-disable-next-line @next/next/no-img-element -- JPEG nhỏ do API tạo, không qua next/image
          <img
            src={`/api/v1/jobs/${encodeURIComponent(job.job_id)}/thumbnail.jpg`}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setThumbnailFailed(true)}
            className="absolute inset-0 size-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 grid size-full place-items-center text-ink-subtle">
            <Film className="size-8" aria-hidden />
          </div>
        )}
        <Badge tone={status.tone} className="absolute top-3 right-3 shadow-sm">
          {status.active && <span className="studio-pulse size-1.5 rounded-full bg-current" aria-hidden />}
          {status.label}
        </Badge>
      </div>
      <div className="flex min-w-0 flex-1 flex-col p-5">
        <h3 className="flex items-center gap-2 truncate text-base font-bold text-ink">
          <span className="truncate">{scene.project.name}</span>
          {scene.project.demo_baseline && <Badge tone="neutral" className="shrink-0" title="Scene có trạng thái đã lưu để quay lại">Đã lưu trạng thái</Badge>}
        </h3>
        <p className="mt-1 truncate text-sm text-ink-muted">
          {scene.project.input_video
            ? `${scene.project.input_video.original_name} · ${formatBytes(scene.project.input_video.size_bytes)}`
            : "Không có video"}
        </p>
        <div className="mt-auto flex items-end justify-between gap-3 pt-5">
          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="text-xs text-ink-subtle"><span className="value-tech">{created}</span></span>
            {scene.project.created_by && actorAttribution("Tạo bởi", scene.project.created_by)}
            {scene.requested_by && scene.requested_by.user_id !== scene.project.created_by?.user_id &&
              actorAttribution("Chạy bởi", scene.requested_by)}
          </div>
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
/** Dạng danh sách: đọc nhanh trạng thái, giai đoạn và mốc thời gian của nhiều scene. */
function SceneTable({ scenes, me, onChanged }: { scenes: SceneSummary[]; me: Me | null; onChanged: () => void }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Scene</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="hidden md:table-cell">Bước hiện tại</TableHead>
            <TableHead className="hidden lg:table-cell">Video</TableHead>
            <TableHead className="hidden xl:table-cell">Thời gian xử lý</TableHead>
            <TableHead className="hidden sm:table-cell">Tạo lúc</TableHead>
            <TableHead className="w-0" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {scenes.map((scene) => {
            const status = sceneSummaryStatus(scene);
            const job = scene.latest_job;
            const targetHref = job
              ? scene.preview_ready
                ? `/scenes/${encodeURIComponent(job.job_id)}`
                : progressHref(job.job_id)
              : null;
            return (
              <TableRow key={scene.project.project_id}>
                <TableCell className="max-w-64 whitespace-normal">
                  <div className="min-w-0 space-y-1.5">
                    {targetHref ? (
                      <Link
                        href={targetHref}
                        className="block truncate font-medium hover:text-ember-strong hover:underline"
                      >
                        {scene.project.name}
                      </Link>
                    ) : (
                      <span className="block truncate font-medium">{scene.project.name}</span>
                    )}
                    {scene.project.created_by && actorAttribution("Tạo bởi", scene.project.created_by)}
                    {scene.requested_by && scene.requested_by.user_id !== scene.project.created_by?.user_id &&
                      actorAttribution("Chạy bởi", scene.requested_by)}
                  </div>
                </TableCell>
                <TableCell>
                  <Badge tone={status.tone}>{status.label}</Badge>
                </TableCell>
                <TableCell className="hidden text-ink-muted md:table-cell">
                  {job
                    ? job.status === "SUCCEEDED"
                      ? "Hoàn tất"
                      : job.current_stage
                        ? (stageMeta(job.current_stage)?.title ?? job.current_stage)
                        : "—"
                    : "—"}
                </TableCell>
                <TableCell className="hidden max-w-56 truncate text-ink-muted lg:table-cell">
                  {scene.project.input_video?.original_name ?? "—"}
                </TableCell>
                <TableCell className="hidden text-xs value-tech text-ink-muted xl:table-cell">
                  {processingTime(scene)}
                </TableCell>
                <TableCell className="hidden text-xs value-tech text-ink-muted sm:table-cell">
                  {scene.project.created_at ? DATE.format(new Date(scene.project.created_at)) : "—"}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-3">
                    {targetHref && (
                      <Link
                        href={targetHref}
                        className="font-medium whitespace-nowrap text-ember-strong hover:underline"
                      >
                        {scene.preview_ready ? "Mở scene" : "Xem tiến trình"}
                      </Link>
                    )}
                    {resourceCapabilityAllowed(me, scene.capabilities?.can_delete_project) && (
                      <MoveToTrashButton name={scene.project.name} move={() => moveSceneToTrash(scene.project.project_id)} onMoved={onChanged} />
                    )}
                  </div>
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
