"use client";

/**
 * Scene Graph panel — tree view của `SceneIR.objects[]` (wireframe Screen 2).
 *
 * Chỉ dùng field contract đã có: `state`, `origin`, `active`, `name`, `id`.
 * Filter tab đúng contract: All / Candidate / Confirmed. Không bịa thêm
 * `UNREVIEWED`/`IGNORED`/`NEEDS_CORRECTION`.
 */

import { useState, useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import type { SceneIR, SceneObject } from "@/lib/contracts/api";

type FilterTab = "ALL" | "CANDIDATE" | "CONFIRMED";

interface SceneGraphProps {
  scene: SceneIR;
  selectedObjectId: string | null;
  onSelect: (objectId: string | null) => void;
}

export function SceneGraph({ scene, selectedObjectId, onSelect }: SceneGraphProps) {
  const [filter, setFilter] = useState<FilterTab>("ALL");

  const filtered = useMemo(() => {
    return scene.objects.filter((obj) => (filter === "ALL" ? true : obj.state === filter));
  }, [scene.objects, filter]);

  const environmentCount = scene.environment.geometry_ref ? 1 : 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1">
        <FilterButton active={filter === "ALL"} onClick={() => setFilter("ALL")} label="All" />
        <FilterButton active={filter === "CANDIDATE"} onClick={() => setFilter("CANDIDATE")} label="Candidate" />
        <FilterButton active={filter === "CONFIRMED"} onClick={() => setFilter("CONFIRMED")} label="Confirmed" />
      </div>

      <ul className="flex max-h-64 flex-col gap-0.5 overflow-y-auto pr-1 text-xs">
        {environmentCount > 0 && (
          <TreeItem
            label="Environment"
            meta="scene"
            active
            selected={false}
            onClick={() => onSelect(null)}
          />
        )}
        {filtered.map((object) => (
          <TreeItem
            key={object.id}
            label={object.name}
            meta={object.origin}
            active={object.active}
            selected={object.id === selectedObjectId}
            onClick={() => onSelect(object.id === selectedObjectId ? null : object.id)}
            stateBadge={object.state}
          />
        ))}
        {filtered.length === 0 && (
          <li className="py-2 text-center text-[10px] text-slate-600">
            Không có object nào trong bộ lọc.
          </li>
        )}
      </ul>

      <p className="text-[10px] text-slate-600">
        {scene.objects.length} object{environmentCount > 0 ? " + environment" : ""}
      </p>
    </div>
  );
}

function FilterButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-2 py-1 text-[10px] font-medium transition-colors ${
        active ? "bg-sky-900/60 text-sky-300" : "text-slate-500 hover:bg-slate-800 hover:text-slate-300"
      }`}
    >
      {label}
    </button>
  );
}

function TreeItem({
  label,
  meta,
  active,
  selected,
  onClick,
  stateBadge,
}: {
  label: string;
  meta: string;
  active: boolean;
  selected: boolean;
  onClick: () => void;
  stateBadge?: SceneObject["state"];
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1 text-left transition-colors ${
          selected ? "bg-sky-900/40 text-sky-300" : "text-slate-300 hover:bg-slate-800 hover:text-slate-100"
        } ${!active ? "opacity-60" : ""}`}
      >
        <span className="flex-1 truncate">{label}</span>
        {stateBadge && (
          <Badge tone={stateBadge === "CONFIRMED" ? "ok" : "warn"} className="shrink-0">
            {stateBadge}
          </Badge>
        )}
        <span className="shrink-0 text-[10px] text-slate-600">{meta}</span>
      </button>
    </li>
  );
}
