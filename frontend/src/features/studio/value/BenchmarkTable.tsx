"use client";

import Link from "next/link";

import { figureText, p2Label, p4Label, sourceLabel } from "@/features/studio/value/ValueCard";
import type { ValueScorecard } from "@/lib/api/value";

/** Nhãn nguồn dữ liệu của scene, theo cột "Nguồn" của Playbook. */
export const DATA_SOURCE_LABEL: Record<string, string> = {
  self_capture: "Tự quay",
  hf_room: "HF room",
  synthetic: "Tổng hợp",
};

/** Một dòng một scene, đúng thứ tự cột của CSV (T-032). Ô thiếu dữ liệu hiện "chưa đo được", không phải 0. */
export function BenchmarkTable({ rows }: { rows: ValueScorecard[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-paper text-xs text-ink-subtle">
          <tr>
            <th className="px-3 py-2 font-semibold">Scene</th>
            <th className="px-3 py-2 font-semibold">Nguồn</th>
            <th className="px-3 py-2 font-semibold">Phần cứng</th>
            <th className="px-3 py-2 text-right font-semibold">Máy (ph)</th>
            <th className="px-3 py-2 text-right font-semibold">Người (ph)</th>
            <th className="px-3 py-2 text-right font-semibold">Can thiệp</th>
            <th className="px-3 py-2 font-semibold">Khe khớp</th>
            <th className="px-3 py-2 font-semibold">Bỏ sót / Giả</th>
            <th className="px-3 py-2 text-right font-semibold">Sai số KT</th>
            <th className="px-3 py-2 text-right font-semibold">Đổi→thử (ph)</th>
            <th className="px-3 py-2 font-semibold">Nhất quán</th>
            <th className="px-3 py-2 font-semibold">Bậc</th>
            <th className="px-3 py-2 text-right font-semibold">Làm tay (ph)</th>
            <th className="px-3 py-2 font-semibold">Ghi chú</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <BenchmarkRow key={row.job_id} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BenchmarkRow({ row }: { row: ValueScorecard }) {
  const ns = row.north_star;
  const p2Unknown = row.p2.unavailable_reason !== null;
  const noGaps = p2Unknown || row.p2.gaps_checked === 0;
  const gapTitle = p2Unknown ? row.p2.unavailable_reason ?? "" : noGaps ? "chưa có khe kiểm nào được đo" : p2Label(row.p2);
  const gpu = ns.hardware.gpu_name;
  return (
    <tr className="border-t border-line align-top">
      <td className="px-3 py-2 font-medium">
        <Link href={`/scenes/${encodeURIComponent(row.job_id)}`} className="underline-offset-2 hover:underline">
          {row.scene_name}
        </Link>
      </td>
      <td className="px-3 py-2">{DATA_SOURCE_LABEL[row.data_source] ?? "chưa có"}</td>
      <td className="px-3 py-2">{gpu ? String(gpu) : "chưa đo được"}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        <span title={sourceLabel(ns.machine_minutes)}>{figureText(ns.machine_minutes)}</span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        <span title={sourceLabel(ns.hands_on_minutes)}>{figureText(ns.hands_on_minutes)}</span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {ns.interventions_total.value === null ? "chưa đo được" : `${ns.interventions_total.value}`}
      </td>
      <td className="px-3 py-2 tabular-nums" title={gapTitle}>
        {noGaps ? "chưa có" : `${row.p2.gaps_agree}/${row.p2.gaps_checked}`}
      </td>
      <td className="px-3 py-2 tabular-nums">
        {noGaps ? "chưa có" : `${row.p2.missed_obstacles} / ${row.p2.false_obstacles}`}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{figureText(row.p2.max_distance_error_cm)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{figureText(row.p3.edit_to_retest_minutes)}</td>
      <td className="px-3 py-2">{row.p3.consistent === null ? "chưa kiểm" : row.p3.consistent ? "Đạt" : "Không"}</td>
      <td className="px-3 py-2" title={p4Label(row.p4.level)}>
        L{row.p4.level}
        {row.p4.level === 4 && <span className="ml-1 text-xs text-ink-subtle">(khai báo)</span>}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{figureText(row.manual_baseline_minutes)}</td>
      <td className="px-3 py-2 text-ink-muted">{row.notes || ""}</td>
    </tr>
  );
}
