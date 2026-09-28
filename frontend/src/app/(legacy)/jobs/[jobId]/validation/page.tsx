import { JobTabs, PageHeader } from "@/components/shell";
import { Checksum, EmptyState, ErrorState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { CopyButton } from "@/components/ui/copy-button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { getValidation } from "@/lib/api/endpoints";
import type { ValidationCheck, PathResult } from "@/lib/contracts/api";

const RESULT_STYLES: Record<string, string> = {
  PASS: "bg-emerald-900/70 text-emerald-300 border-emerald-900",
  FAIL: "bg-rose-900/70 text-rose-300 border-rose-900",
  CLEAR: "bg-emerald-900/70 text-emerald-300 border-emerald-900",
  BLOCKED: "bg-rose-900/70 text-rose-300 border-rose-900",
};

function ResultBadge({ value }: { value: string }) {
  return (
    <Badge tone={getTone(value)} className={RESULT_STYLES[value] ?? ""}>
      {value}
    </Badge>
  );
}

function getTone(value: string) {
  if (value === "PASS" || value === "CLEAR") return "ok";
  if (value === "FAIL" || value === "BLOCKED") return "danger";
  return "default";
}

export default async function ValidationPage({ params }: PageProps<"/jobs/[jobId]/validation">) {
  const { jobId } = await params;
  const validation = await getValidation(jobId);

  if (!validation.ok) {
    return (
      <>
        <PageHeader title="Validation" subtitle={jobId} />
        <JobTabs jobId={jobId} active="Validation" />
        <ErrorState title="Không tải được báo cáo validation" detail={validation.error.detail} />
      </>
    );
  }

  const { report } = validation.data;

  return (
    <>
      <PageHeader
        title="Validation"
        subtitle={`candidate ${report.candidate_checksum.slice(0, 18)}… · validator ${report.validator_version}`}
      />
      <JobTabs jobId={jobId} active="Validation" />

      {!validation.data.isaac_runtime_proof && (
        <p
          data-testid="no-runtime-proof"
          className="mb-4 rounded-xl border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200"
        >
          <strong>Chưa có bằng chứng chạy simulator thật.</strong> `environment_versions` báo{" "}
          <span className="font-mono">
            {Object.entries(report.environment_versions)
              .map(([key, value]) => `${key}=${value}`)
              .join(", ")}
          </span>
          . Kết quả PASS dưới đây là của fixture, <em>không</em> phải acceptance của Product E2E.
        </p>
      )}

      <Panel className="mb-6">
        <div className="p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400">Overall:</span>
            <ResultBadge value={report.overall_result} />
          </div>
          <p className="mt-2 text-xs text-slate-500">
            <Checksum value={report.report_checksum} label="report checksum" />
          </p>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHeader
            title="Checks"
            subtitle={`${report.checks.length} check · grouped by result`}
          />
          {report.checks.length === 0 ? (
            <div className="p-4">
              <EmptyState message="Không có check nào trong báo cáo." />
            </div>
          ) : (
            <ul className="flex flex-col gap-0.5 p-3">
              {report.checks.map((check) => (
                <CheckItem key={check.check_id} check={check} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Path results" subtitle={`${report.path_results.length} pair`} />
          {report.path_results.length === 0 ? (
            <div className="p-4">
              <EmptyState message="Không có path result nào." />
            </div>
          ) : (
            <ul className="flex flex-col gap-0.5 p-3">
              {report.path_results.map((path) => (
                <PathItem key={path.pair_id} path={path} />
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  );
}

function CheckItem({ check }: { check: ValidationCheck }) {
  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-slate-300">{check.check_id}</span>
          <ResultBadge value={check.result} />
        </div>
      </div>
      <p className="mt-1.5 text-xs text-slate-400">{check.message}</p>
      {check.evidence_refs.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[10px] text-slate-500 hover:text-slate-400">
            Evidence refs ({check.evidence_refs.length})
          </summary>
          <ul className="mt-1 flex flex-col gap-0.5">
            {check.evidence_refs.map((ref) => (
              <li
                key={ref.artifact_uri}
                className="flex items-center gap-1.5 font-mono text-[10px] text-slate-500"
              >
                <span className="truncate" title={ref.artifact_uri}>
                  {ref.artifact_uri}
                </span>
                <span>·</span>
                <span title={ref.artifact_checksum}>{ref.artifact_checksum.slice(0, 18)}…</span>
                <CopyButton value={ref.artifact_uri} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function PathItem({ path }: { path: PathResult }) {
  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-slate-300">{path.pair_id}</span>
          <ResultBadge value={path.result} />
        </div>
      </div>
      <p className="mt-1.5 text-xs text-slate-400">{path.message}</p>
      {path.evidence_refs.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[10px] text-slate-500 hover:text-slate-400">
            Evidence refs ({path.evidence_refs.length})
          </summary>
          <ul className="mt-1 flex flex-col gap-0.5">
            {path.evidence_refs.map((ref) => (
              <li
                key={ref.artifact_uri}
                className="flex items-center gap-1.5 font-mono text-[10px] text-slate-500"
              >
                <span className="truncate" title={ref.artifact_uri}>
                  {ref.artifact_uri}
                </span>
                <CopyButton value={ref.artifact_uri} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}
