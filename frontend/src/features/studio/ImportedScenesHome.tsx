"use client";

import { errorMessage } from "@/lib/ui-error";
import { GAUSSIAN_EDIT_ENABLED } from "@/features/studio/scene/state";

import { ArrowRight, Box, FolderDown, LayoutGrid, List, LogIn, Plus, RefreshCw, Search } from "lucide-react";
import { GuardedLink as Link } from "@/features/shell/NavigationGuard";
import { useCallback, useMemo, useState } from "react";

import { Input } from "@/components/shadcn/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/shadcn/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/shadcn/toggle-group";
import { Badge, Button, Card, EmptyState, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { usePolling } from "@/features/studio/usePolling";
import { canEdit, resourceCapabilityAllowed, type Me } from "@/lib/api/auth";
import { listImports, moveImportToTrash } from "@/lib/api/studio";
import { MoveToTrashButton } from "@/features/studio/trash/MoveToTrashButton";
import { cn } from "@/lib/cn";
import type { ImportedScene } from "@/lib/contracts/studio";
import { useListState, pageSlice, ListPagination, SortControl } from "@/features/studio/ListControls";

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

function importSourceLabel(kind: ImportedScene["input_kind"]): string {
  if (kind === "gaussian_sog") return "SOG";
  if (kind === "gaussian_ply_colmap") return "PLY + COLMAP";
  return "PLY";
}

function importStatusView(item: ImportedScene): { label: string; tone: "sage" | "ochre" | "rust" | "neutral"; active: boolean } {
  if (item.status === "READY") {
    return { label: GAUSSIAN_EDIT_ENABLED ? "Mở xem/chỉnh" : "Mở xem", tone: "sage", active: false };
  }
  if (item.status === "FAILED") {
    return { label: "Lỗi nén", tone: "rust", active: false };
  }
  if (item.status === "CANCELLED") {
    return { label: "Đã hủy", tone: "neutral", active: false };
  }
  const opStatus = item.operation?.status;
  if (opStatus === "WAITING") {
    return { label: "Đang chờ tài nguyên", tone: "ochre", active: true };
  }
  if (opStatus === "QUEUED") {
    return { label: "Đang chờ worker", tone: "ochre", active: true };
  }
  return { label: "Đang nén SOG…", tone: "ochre", active: true };
}

export function ImportedScenesHome() {
  const [imports, setImports] = useState<ImportedScene[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { me } = useAuth();
  const signedIn = canEdit(me);

  const load = useCallback(async () => {
    if (!signedIn) return;
    const result = await listImports();
    if (result.ok) {
      setImports(result.data.imports);
      setError(null);
    } else {
      setError(errorMessage(result.error));
    }
  }, [signedIn]);

  const { query, setQuery, view, setView, sort, setSort, params, update } = useListState();

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (imports ?? [])
      .filter((item) => !needle || item.name.toLowerCase().includes(needle))
      .sort((a, b) =>
        sort === "name"
          ? a.name.localeCompare(b.name, "vi")
          : Date.parse(b.created_at) - Date.parse(a.created_at),
      );
  }, [imports, query, sort]);

  const pagination = pageSlice(shown, params.get("page"), 12);
  const anyActive = imports?.some((item) => item.status === "PACKAGING") ?? false;
  usePolling(load, signedIn && anyActive ? 4000 : 20000, true);

  return (
    <main className="mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-ink">Scenes đã import</h1>
          <p className="mt-1.5 max-w-xl text-[15px] leading-relaxed text-ink-muted">
            Quản lý các scene 3DGS nạp từ file PLY hoặc SOG (chỉ xem và chỉnh sửa, không chạy pipeline reconstruction).
          </p>
        </div>
        <div>
          <Link href="/new" className={buttonVariants({ size: "sm" })}>
            <Plus className="size-4" aria-hidden />
            <span>Import scene mới</span>
          </Link>
        </div>
      </div>

      {!signedIn && me !== null && (
        <Notice className="mt-8">
          Scene đã import chỉ hiển thị sau khi đăng nhập.
        </Notice>
      )}

      {signedIn && error && (
        <Notice tone="rust" icon={<RefreshCw aria-hidden />} className="mt-8">
          Không tải được danh sách scene import: {error}. Trang sẽ tự thử lại.
        </Notice>
      )}

      {me !== null && !signedIn && (
        <div className="mt-8">
          <EmptyState
            icon={<LogIn aria-hidden />}
            title="Đăng nhập để xem scene đã import"
            action={
              <Link href="/login?next=/imports" className={buttonVariants({})}>
                Đăng nhập
              </Link>
            }
          >
            Đăng nhập để tải lên và quản lý các scene 3DGS của bạn.
          </EmptyState>
        </div>
      )}

      {me === null && <p role="status" className="mt-8 text-sm text-ink-muted">Đang kiểm tra quyền truy cập…</p>}

      {signedIn && imports === null && !error && (
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Đang tải">
          {[0, 1, 2].map((key) => (
            <div key={key} className="h-44 animate-pulse rounded-2xl border border-line bg-paper-raised motion-reduce:animate-none" />
          ))}
        </div>
      )}

      {signedIn && imports && imports.length === 0 && (
        <div className="mt-8">
          <EmptyState
            icon={<FolderDown className="size-8 text-ink-muted" aria-hidden />}
            title="Chưa có scene import nào"
            action={
              <Link href="/new" className={buttonVariants({})}>
                <Plus className="size-4" aria-hidden />
                <span>Import file 3DGS ngay</span>
              </Link>
            }
          >
            Tải lên file PLY hoặc SOG để xem bản 3DGS trực tiếp trong trình xem thời gian thực.
          </EmptyState>
        </div>
      )}

      {signedIn && imports && imports.length > 0 && (
        <section aria-labelledby="imports-list-heading" className="mt-8">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
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
              <SortControl value={sort} onChange={setSort} />
              <ToggleGroup
                type="single"
                value={view}
                onValueChange={(val) => {
                  if (val) setView(val as "grid" | "list");
                }}
                variant="outline"
                size="sm"
                aria-label="Chế độ hiển thị"
              >
                <ToggleGroupItem value="grid" aria-label="Lưới">
                  <LayoutGrid className="size-4" aria-hidden />
                </ToggleGroupItem>
                <ToggleGroupItem value="list" aria-label="Danh sách">
                  <List className="size-4" aria-hidden />
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
            <span className="text-sm text-ink-subtle">{imports.length} scene</span>
          </div>

          {shown.length === 0 ? (
            <p className="mt-8 text-sm text-ink-muted">Không tìm thấy scene import nào khớp với từ khóa tìm kiếm.</p>
          ) : view === "grid" ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {pagination.items.map((item) => (
                <ImportCard key={item.import_id} item={item} me={me} onChanged={() => void load()} />
              ))}
            </div>
          ) : (
            <ImportTable items={pagination.items} me={me} onChanged={() => void load()} />
          )}

          <ListPagination
            page={pagination.page}
            totalPages={pagination.totalPages}
            total={shown.length}
            onChange={(page) => update({ page: String(page) })}
          />
        </section>
      )}
    </main>
  );
}

function ImportCard({ item, me, onChanged }: { item: ImportedScene; me: Me | null; onChanged: () => void }) {
  const status = importStatusView(item);
  const created = item.created_at ? DATE.format(new Date(item.created_at)) : null;

  return (
    <Card className="group flex flex-col justify-between overflow-hidden p-5 transition-[border-color,box-shadow] duration-200 hover:border-line-strong hover:shadow-md">
      <div>
        <div className="flex items-start justify-between gap-2">
          <Badge tone="neutral" className="font-mono text-xs uppercase">
            {importSourceLabel(item.input_kind)}
          </Badge>
          <Badge tone={status.tone} className="shadow-xs">
            {status.active && <span className="studio-pulse size-1.5 rounded-full bg-current mr-1" aria-hidden />}
            {status.label}
          </Badge>
        </div>
        <h3 className="mt-3 truncate text-base font-bold text-ink">
          <Link
            href={`/imports/${item.import_id}`}
            className="hover:text-ember-strong hover:underline focus-visible:outline-hidden"
          >
            {item.name}
          </Link>
        </h3>
        <div className="mt-2 flex flex-col gap-1">
          {item.created_by_name && (
            <ActorAttribution label="Tạo bởi" name={item.created_by_name} role={item.created_by_role} />
          )}
          <span className="text-xs text-ink-subtle value-tech">{created}</span>
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between border-t border-line/50 pt-3">
        <Link
          href={`/imports/${item.import_id}`}
          className="flex items-center gap-1 text-sm font-medium text-ink-muted transition-colors group-hover:text-ember-strong"
        >
          <span>{item.status === "READY" ? "Mở scene" : "Xem chi tiết"}</span>
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
        {resourceCapabilityAllowed(me, item.capabilities?.can_delete) && (
          <MoveToTrashButton
            name={item.name}
            move={() => moveImportToTrash(item.import_id)}
            onMoved={onChanged}
          />
        )}
      </div>
    </Card>
  );
}

function ImportTable({ items, me, onChanged }: { items: ImportedScene[]; me: Me | null; onChanged: () => void }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Tên scene</TableHead>
            <TableHead>Định dạng</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="hidden md:table-cell">Người tạo</TableHead>
            <TableHead className="hidden sm:table-cell">Ngày tạo</TableHead>
            <TableHead className="w-0 text-right">Thao tác</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => {
            const status = importStatusView(item);
            const created = item.created_at ? DATE.format(new Date(item.created_at)) : "—";
            return (
              <TableRow key={item.import_id}>
                <TableCell className="max-w-64">
                  <Link
                    href={`/imports/${item.import_id}`}
                    className="block truncate font-medium text-ink hover:text-ember-strong hover:underline"
                  >
                    {item.name}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge tone="neutral">{importSourceLabel(item.input_kind)}</Badge>
                </TableCell>
                <TableCell>
                  <Badge tone={status.tone}>{status.label}</Badge>
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {item.created_by_name ? (
                    <ActorAttribution label="Tạo bởi" name={item.created_by_name} role={item.created_by_role} />
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell className="hidden text-xs text-ink-subtle value-tech sm:table-cell">
                  {created}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    <Link
                      href={`/imports/${item.import_id}`}
                      className="font-medium whitespace-nowrap text-ember-strong hover:underline"
                    >
                      {item.status === "READY" ? "Mở scene" : "Xem"}
                    </Link>
                    {resourceCapabilityAllowed(me, item.capabilities?.can_delete) && (
                      <MoveToTrashButton
                        name={item.name}
                        move={() => moveImportToTrash(item.import_id)}
                        onMoved={onChanged}
                      />
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
