import { JobTabs, PageHeader } from "@/components/shell";
import { Checksum, ErrorState } from "@/components/states";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { getJob, getReview, getValidation } from "@/lib/api/endpoints";
import { ReleasePanel } from "@/features/review/ReleasePanel";

/**
 * Release page — PRODUCT-11: seal exact candidate → ReleaseManifest.
 *
 * Chỉ hiện nút release khi:
 * - Review đã APPROVE.
 * - Candidate checksum khớp validation report checksum trong approval.
 * Mọi điều kiện trên được kiểm ở backend; UI chỉ hiện affordance.
 */
export default async function ReleasePage({ params }: PageProps<"/jobs/[jobId]/release">) {
  const { jobId } = await params;
  const [job, review, validation] = await Promise.all([
    getJob(jobId),
    getReview(jobId),
    getValidation(jobId),
  ]);

  if (!job.ok) {
    return (
      <>
        <PageHeader title="Release" subtitle={jobId} />
        <JobTabs jobId={jobId} active="Release" />
        <ErrorState title="Không tải được job" detail={job.error.detail} />
      </>
    );
  }

  const approved = review.ok && review.data.approval.decision === "APPROVE";
  const checksumMatch =
    review.ok &&
    validation.ok &&
    review.data.approval.validation_report_checksum === validation.data.report.report_checksum;

  return (
    <>
      <PageHeader title="Release" subtitle={`job: ${jobId}`} />
      <JobTabs jobId={jobId} active="Release" />

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        {/* Release panel */}
        <ReleasePanel
          jobId={jobId}
          approved={approved}
          checksumMatch={checksumMatch ?? false}
          approvalRecord={review.ok ? review.data.approval : null}
          jobStatus={job.data.status}
        />

        {/* Sidebar info */}
        <aside className="flex flex-col gap-4">
          <Panel>
            <div className="p-4">
              <PanelHeader title="Điều kiện release" />
              <ul className="mt-2 space-y-2">
                <Condition
                  ok={job.data.status === "SUCCEEDED"}
                  label={`Job SUCCEEDED (hiện: ${job.data.status})`}
                />
                <Condition ok={approved} label="Approval decision = APPROVE" />
                <Condition
                  ok={checksumMatch ?? false}
                  label="Candidate checksum khớp validation report"
                />
              </ul>
            </div>
          </Panel>

          <Panel>
            <div className="p-4">
              <PanelHeader title="Checksums sẽ seal" />
              <ul className="mt-2 space-y-1.5">
                <li>
                  <Checksum
                    value={review.ok ? review.data.approval.candidate_checksum : null}
                    label="candidate"
                  />
                </li>
                <li>
                  <Checksum
                    value={review.ok ? review.data.approval.validation_report_checksum : null}
                    label="validation"
                  />
                </li>
                <li>
                  <Checksum
                    value={review.ok ? review.data.approval.record_checksum : null}
                    label="approval record"
                  />
                </li>
              </ul>
            </div>
          </Panel>

          <Panel>
            <div className="p-4">
              <PanelHeader title="Fake stub note" />
              <p className="text-[10px] text-slate-600">
                Endpoint <span className="font-mono">/release POST</span> là fake — trả 404 cho đến
                khi PRODUCT-11 backend implement. ReleaseManifest schema đã được định sẵn trong
                contract.
              </p>
            </div>
          </Panel>
        </aside>
      </div>
    </>
  );
}

function Condition({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className="flex items-start gap-2 text-xs">
      <span className={`mt-0.5 shrink-0 ${ok ? "text-emerald-400" : "text-slate-600"}`}>
        {ok ? "✓" : "○"}
      </span>
      <span className={ok ? "text-slate-300" : "text-slate-600"}>{label}</span>
    </li>
  );
}
