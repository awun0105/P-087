import { JobTabs, PageHeader } from "@/components/shell";
import { Checksum, EmptyState, ErrorState } from "@/components/states";
import { getValidation } from "@/lib/api/endpoints";

const RESULT_STYLES: Record<string, string> = {
  PASS: "bg-emerald-900 text-emerald-200",
  FAIL: "bg-rose-900 text-rose-200",
  CLEAR: "bg-emerald-900 text-emerald-200",
  BLOCKED: "bg-rose-900 text-rose-200",
};

function ResultBadge({ value }: { value: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${RESULT_STYLES[value] ?? "bg-slate-700 text-slate-200"}`}>
      {value}
    </span>
  );
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
          className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200"
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

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">
          Overall: <ResultBadge value={report.overall_result} />
        </h2>
        <p className="text-xs text-slate-500">
          <Checksum value={report.report_checksum} label="report checksum" />
        </p>
      </section>

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Checks</h2>
        {report.checks.length === 0 ? (
          <EmptyState message="Không có check nào trong báo cáo." />
        ) : (
          <ul className="flex flex-col gap-2">
            {report.checks.map((check) => (
              <li key={check.check_id} className="rounded border border-slate-800 bg-slate-900/40 p-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-300">{check.check_id}</span>
                  <ResultBadge value={check.result} />
                </div>
                <p className="mt-1 text-xs text-slate-400">{check.message}</p>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {check.evidence_refs.map((ref) => (
                    <li key={ref.artifact_uri} className="font-mono text-[10px] text-slate-500">
                      {ref.artifact_uri} · {ref.artifact_checksum.slice(0, 18)}…
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Path results</h2>
        {report.path_results.length === 0 ? (
          <EmptyState message="Không có path result nào." />
        ) : (
          <ul className="flex flex-col gap-2">
            {report.path_results.map((path) => (
              <li key={path.pair_id} className="rounded border border-slate-800 bg-slate-900/40 p-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-300">{path.pair_id}</span>
                  <ResultBadge value={path.result} />
                </div>
                <p className="mt-1 text-xs text-slate-400">{path.message}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
