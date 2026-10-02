"use client";
import { Button } from "@/components/studio/primitives";
import { useUrlState } from "@/features/studio/useUrlState";
import { STATUS_FILTERS, type SceneStatusGroup } from "@/features/studio/sceneStatus";

export function useListState() {
  const { params, update } = useUrlState();
  const rawFilter = params.get("filter");
  const filter = STATUS_FILTERS.some((item) => item.value === rawFilter) ? rawFilter as SceneStatusGroup | "all" : "all";
  const resetPages = { page: null, importsPage: null, samplesPage: null };
  return {
    params, update, query: params.get("q") ?? "", filter,
    view: params.get("view") === "list" ? "list" as const : "grid" as const,
    sort: params.get("sort") === "name" ? "name" as const : "newest" as const,
    setQuery: (value: string) => update({ q: value, ...resetPages }, true),
    setFilter: (value: SceneStatusGroup | "all") => update({ filter: value === "all" ? null : value, ...resetPages }),
    setView: (value: "grid" | "list") => update({ view: value }),
    setSort: (value: string) => update({ sort: value, ...resetPages }),
    clear: () => update({ q: null, filter: null, ...resetPages }),
  };
}
/** Trang sai/ngoài miền được clamp, không tạo màn rỗng giả. */
export function pageSlice<T>(items: T[], rawPage: string | null, size: number) {
  const totalPages = Math.max(1, Math.ceil(items.length / size));
  const requested = Number(rawPage);
  const page = Number.isSafeInteger(requested) && requested > 0 ? Math.min(requested, totalPages) : 1;
  return { items: items.slice((page - 1) * size, page * size), page, totalPages };
}
export function ListPagination({ page, totalPages, total, onChange }: { page: number; totalPages: number; total: number; onChange: (value: number) => void }) {
  if (total === 0) return null;
  return <nav aria-label="Phân trang" className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
    <p className="text-ink-muted">{total} mục · Trang {page}/{totalPages}</p>
    <div className="flex gap-2"><Button size="sm" variant="secondary" disabled={page === 1} onClick={() => onChange(page - 1)}>Trang trước</Button><Button size="sm" variant="secondary" disabled={page === totalPages} onClick={() => onChange(page + 1)}>Trang sau</Button></div>
  </nav>;
}
export function SortControl({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <label className="flex items-center gap-2 text-sm text-ink-muted">Sắp xếp<select aria-label="Sắp xếp" value={value} onChange={(event) => onChange(event.target.value)} className="h-9 rounded-lg border border-line bg-paper-raised px-2 text-ink"><option value="newest">Mới nhất</option><option value="name">Tên A–Z</option></select></label>;
}
