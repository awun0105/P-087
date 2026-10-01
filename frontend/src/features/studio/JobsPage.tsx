"use client";

import { ListChecks, LogIn, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { Input } from "@/components/shadcn/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/shadcn/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/shadcn/toggle-group";
import { Badge, EmptyState, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { STATUS_FILTERS, sceneStatus, type SceneStatusGroup } from "@/features/studio/sceneStatus";
import { stageMeta } from "@/features/studio/stages";
import { usePolling } from "@/features/studio/usePolling";
import { canEdit } from "@/lib/api/auth";
import { listScenes } from "@/lib/api/studio";
import type { SceneSummary } from "@/lib/contracts/studio";

const TIME = new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" });

function duration(start: string, end: string | null, now: number): string {
  const seconds = Math.max(0, Math.round(((end ? Date.parse(end) : now) - Date.parse(start)) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} giờ ${minutes % 60} phút` : `${minutes} phút ${seconds % 60} giây`;
}

/**
 * Jobs (S04): lần xử lý mới nhất của mỗi scene, dựng từ `/scenes` (PRODUCT.md D-06). Chỉ đọc —
 * huỷ/thử lại nằm trong màn tiến trình của scene; không có kéo đổi trạng thái hay xếp lịch.
 */
export function JobsPage() {
  const { me } = useAuth();
  const signedIn = canEdit(me);
  const [scenes, setScenes] = useState<SceneSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<SceneStatusGroup | "all">("all");
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    if (!signedIn) return;
    const result = await listScenes();
    setNow(Date.now());
    if (result.ok) {
      setScenes(result.data.scenes);
      setError(null);
    } else {
      setError(result.error.detail);
    }
  }, [signedIn]);
  const jobs = useMemo(
    () =>
      (scenes ?? [])
        .filter((scene) => scene.latest_job !== null)
        .sort((a, b) => Date.parse(b.latest_job!.started_at ?? "") - Date.parse(a.latest_job!.started_at ?? "")),
    [scenes],
  );
  const anyActive = jobs.some((scene) => sceneStatus(scene.latest_job, scene.preview_ready).active);
  // Bật poll khi đã biết người dùng xem được: effect khởi động lại và tải ngay, không đợi chu kỳ sau.
  usePolling(load, anyActive ? 5000 : 20000, signedIn);

  const shown = jobs.filter((scene) => {
    const needle = query.trim().toLowerCase();
    return (
      (!needle || scene.project.name.toLowerCase().includes(needle)) &&
      (filter === "all" || sceneStatus(scene.latest_job, scene.preview_ready).group === filter)
    );
  });

  return (
    <main className="mx-auto max-w-6xl px-4 pt-8 pb-16 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
      <p className="mt-1 text-sm text-ink-muted">Lần xử lý mới nhất của mỗi scene. Mở một dòng để xem tiến trình, huỷ hoặc thử lại.</p>
      {me !== null && !signedIn && (
        <EmptyState
          className="mt-8"
          icon={<LogIn aria-hidden />}
          title="Đăng nhập để xem các lần xử lý của nhóm"
          action={
            <Link href="/login?next=/jobs" className={buttonVariants({})}>
              Đăng nhập
            </Link>
          }
        />
      )}
      {signedIn && error && (
        <Notice tone="rust" icon={<RefreshCw aria-hidden />} className="mt-6">
          Không tải được danh sách: {error}. Đang hiển thị dữ liệu lần tải trước; trang sẽ tự thử lại.
        </Notice>
      )}
      {signedIn && (
        <div className="mt-6 mb-4 flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm theo tên scene" aria-label="Tìm theo tên scene" className="pl-8" />
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
        </div>
      )}
      {signedIn && scenes === null && !error && <p className="text-sm text-ink-muted" role="status">Đang tải…</p>}
      {signedIn && scenes !== null && jobs.length === 0 && (
        <EmptyState className="mt-4" icon={<ListChecks aria-hidden />} title="Chưa có lần xử lý nào">
          Vào <Link href="/scenes" className="font-medium text-ember-strong hover:underline">Scenes</Link> và chọn “Scene mới”, rồi dựng từ video để bắt đầu một lần xử lý.
        </EmptyState>
      )}
      {signedIn && jobs.length > 0 && shown.length === 0 && <p className="rounded-xl border border-line p-6 text-center text-sm text-ink-muted">Không có lần xử lý khớp bộ lọc. <button type="button" onClick={() => { setQuery(""); setFilter("all"); }} className="font-medium text-ember-strong hover:underline">Xoá bộ lọc</button></p>}
      {signedIn && shown.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scene</TableHead>
                <TableHead>Trạng thái</TableHead>
                <TableHead className="hidden md:table-cell">Bước hiện tại</TableHead>
                <TableHead className="hidden sm:table-cell">Bắt đầu</TableHead>
                <TableHead className="hidden lg:table-cell">Tổng thời gian</TableHead>
                <TableHead className="hidden w-0 sm:table-cell" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((scene) => {
                const job = scene.latest_job!;
                const status = sceneStatus(job, scene.preview_ready);
                return (
                  <TableRow key={job.job_id}>
                    <TableCell className="max-w-44 sm:max-w-64">
                      {/* Tên là liên kết: màn hẹp ẩn cột "Mở tiến trình" nhưng vẫn mở được scene. */}
                      <Link
                        href={`/scenes/${encodeURIComponent(job.job_id)}`}
                        className="block truncate font-medium hover:text-ember-strong hover:underline"
                      >
                        {scene.project.name}
                      </Link>
                      <p className="truncate font-mono text-xs text-ink-subtle">{job.job_id}</p>
                    </TableCell>
                    <TableCell>
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </TableCell>
                    <TableCell className="hidden text-ink-muted md:table-cell">{job.status === "SUCCEEDED" ? "Hoàn tất" : job.current_stage ? (stageMeta(job.current_stage)?.title ?? job.current_stage) : "—"}</TableCell>
                    <TableCell className="hidden text-ink-muted sm:table-cell">{job.started_at ? TIME.format(new Date(job.started_at)) : "—"}</TableCell>
                    <TableCell className="hidden text-ink-muted lg:table-cell">
                      {status.group === "action"
                        ? "Đang chờ bạn"
                        : job.started_at
                          ? // Manifest không có thời gian từng bước: job đã qua bước tỉ lệ mét thì tổng gồm cả lúc
                            // chờ người chọn điểm — ghi rõ, không trình bày như thời gian máy chạy.
                            `${duration(job.started_at, job.completed_at, now)}${job.completed_at ? "" : " (đang chạy)"}${
                              job.stage_artifacts.some((item) => item.stage_id === "ST-METRIC-CANONICALIZE") ? " · gồm lúc chờ bạn" : ""
                            }`
                          : "—"}
                    </TableCell>
                    <TableCell className="hidden text-right sm:table-cell">
                      <Link href={`/scenes/${encodeURIComponent(job.job_id)}`} className="font-medium whitespace-nowrap text-ember-strong hover:underline">
                        Mở scene
                      </Link>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </main>
  );
}
