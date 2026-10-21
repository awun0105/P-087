"use client";

import { FileSearch } from "lucide-react";

import { CopyButton } from "@/components/studio/feedback";
import { Badge, Notice } from "@/components/studio/primitives";
import { TraceList } from "@/features/studio/TraceList";
import type { EvidenceRefView, ReviewStateView } from "@/lib/api/studio";

const collisionStateLabels = {
  observed_static: "đã quan sát tĩnh",
  unobserved: "chưa quan sát",
  inferred: "suy luận",
  motion_suspected: "nghi có chuyển động",
} as const;

const RESULT: Record<string, { label: string; tone: "sage" | "rust" }> = {
  PASS: { label: "Đạt", tone: "sage" },
  FAIL: { label: "Không đạt", tone: "rust" },
  ERROR: { label: "Lỗi", tone: "rust" },
  CLEAR: { label: "Thông", tone: "sage" },
  BLOCKED: { label: "Bị chặn", tone: "rust" },
};

/** Kết quả dạng nhãn tiếng Việt kèm mã gốc của contract; mã lạ hiện nguyên văn với tông trung tính. */
function ResultBadge({ value }: { value: string }) {
  const known = RESULT[value];
  return <Badge tone={known?.tone ?? "neutral"}>{known ? `${known.label} · ${value}` : value}</Badge>;
}

/**
 * Báo cáo validation của đúng gói thuộc revision hiện tại: từng check, từng cặp Start–Goal,
 * bằng chứng đi kèm và "Nguồn kết quả" để đối chiếu checksum. Chỉ đọc; quyết định duyệt nằm ở `ReviewPanel`.
 *
 * Cờ proof chỉ do backend đặt khi selected worker run, report và RuntimeManifest đã xác minh khớp.
 * Environment version chỉ để hiển thị; không thể tự cấp trust. Cờ vắng mặt cũng fail closed.
 */
export function ValidationReportCard({ state }: { state: ReviewStateView }) {
  const report = state.validation;
  if (!report) return null;
  const environment = Object.entries(report.environment_versions);
  const collisionSupport = new Map((report.collision_path_support ?? []).map((item) => [item.pair_id, item]));
  const otherCandidate = Boolean(report.candidate_checksum && state.record.candidate_checksum && report.candidate_checksum !== state.record.candidate_checksum);
  return (
    <section className="space-y-4 p-5 text-sm" aria-label="Báo cáo kiểm tra">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 font-bold text-ink">
          <FileSearch className="size-4" aria-hidden /> Báo cáo kiểm tra
        </h3>
        <ResultBadge value={report.overall_result} />
      </div>
      {state.isaac_runtime_proof !== true && (
        <Notice tone="ochre">
          <p className="font-semibold text-ink">Chưa có bằng chứng chạy Isaac Sim thật.</p>
          <p className="mt-1">
            Báo cáo ghi môi trường{" "}
            <code className="font-mono">{environment.length > 0 ? environment.map(([key, version]) => `${key}=${version}`).join(", ") : "trống"}</code>.
            Kết quả dưới đây không phải kết luận của mô phỏng; không dùng làm căn cứ nghiệm thu.
          </p>
        </Notice>
      )}
      {otherCandidate && <Notice tone="rust">Báo cáo này thuộc một gói khác. Tải lại trang trước khi quyết định.</Notice>}
      <div>
        <h4 className="label-tech text-ink-muted">Check ({report.checks.length})</h4>
        <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
          {report.checks.map((check) => (
            <ResultRow key={check.check_id} id={check.check_id} result={check.result} message={check.message} evidence={check.evidence_refs} needsAcceptance={state.warning_ids.includes(check.check_id)} />
          ))}
        </ul>
      </div>
      <div>
        <h4 className="label-tech text-ink-muted">Start–Goal ({report.path_results.length})</h4>
        {report.path_results.length === 0 ? (
          <p className="mt-2 text-ink-muted">Báo cáo không có cặp Start–Goal nào.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
            {report.path_results.map((path) => {
              const support = collisionSupport.get(path.pair_id);
              const coverage = !report.collision_quality_ref
                ? "Chưa có báo cáo chất lượng va chạm; CLEAR chỉ là kết quả quan sát."
                : support
                  ? `Coverage collider ${(support.coverage_fraction * 100).toFixed(1)}% · ${collisionStateLabels[support.state]}`
                  : "Chưa kiểm chất lượng va chạm cho cặp này; CLEAR chưa chắc an toàn.";
              const message = [path.message, coverage].filter(Boolean).join(" · ");
              return (
                <ResultRow
                  key={path.pair_id}
                  id={path.pair_id}
                  result={path.result}
                  message={message}
                  evidence={[
                    ...path.evidence_refs,
                    ...(support?.diagnostic_ref ? [support.diagnostic_ref] : []),
                  ]}
                  needsAcceptance={
                    state.warning_ids.includes(`path:${path.pair_id}`) ||
                    state.warning_ids.includes(`collision-support:${path.pair_id}`)
                  }
                />
              );
            })}
          </ul>
        )}
      </div>
      <details className="rounded-lg border border-line px-3 py-2">
        <summary className="cursor-pointer font-medium text-ink focus-visible:outline-2 focus-visible:outline-ember">Nguồn kết quả</summary>
        <div className="mt-3 space-y-2">
          <p className="text-xs text-ink-muted">Dùng để đối chiếu báo cáo với đúng gói.</p>
          <TraceList
            rows={[
              { label: "Revision scene", value: state.record.scene_revision },
              { label: "Mã gói", value: report.candidate_checksum },
              { label: "Mã báo cáo", value: report.report_checksum },
              { label: "Báo cáo chất lượng va chạm", value: report.collision_quality_ref?.artifact_uri ?? "chưa có" },
              { label: "Validator", value: report.validator_version },
              ...environment.map(([key, version]) => ({ label: `Môi trường · ${key}`, value: version })),
            ]}
          />
        </div>
      </details>
    </section>
  );
}

function ResultRow({ id, result, message, evidence, needsAcceptance }: { id: string; result: string; message: string | null; evidence: EvidenceRefView[]; needsAcceptance: boolean }) {
  return (
    <li className="px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <code className="font-mono text-xs font-medium text-ink">{id}</code>
        <ResultBadge value={result} />
        {needsAcceptance && <Badge tone="ochre">Cần người duyệt chấp nhận</Badge>}
      </div>
      {message && <p className="mt-1 text-ink-muted">{message}</p>}
      {evidence.length === 0 ? (
        <p className="mt-1 text-xs text-ink-subtle">Không kèm bằng chứng.</p>
      ) : (
        <details className="mt-1.5 text-xs">
          <summary className="cursor-pointer text-ink-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-ember">Bằng chứng ({evidence.length})</summary>
          <ul className="mt-1.5 space-y-1">
            {evidence.map((reference) => (
              <li key={reference.artifact_uri} className="flex items-start gap-1">
                <code className="min-w-0 font-mono break-all text-ink">{reference.artifact_uri}</code>
                <CopyButton value={reference.artifact_uri} label="đường dẫn bằng chứng" />
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}
