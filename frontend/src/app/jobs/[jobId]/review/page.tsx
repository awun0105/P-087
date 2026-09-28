import { JobTabs, PageHeader } from "@/components/shell";
import { Checksum, ErrorState } from "@/components/states";
import { Banner } from "@/components/ui/banner";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { getReview, getValidation } from "@/lib/api/endpoints";
import { ReviewLifecyclePanel } from "@/features/review/ReviewLifecycle";

/**
 * Màn hình review — PRODUCT-10.
 *
 * Hiển thị state machine, quyết định, ràng buộc checksum và action buttons.
 * Cờ `synthetic_authorization` phải nằm cạnh quyết định để không đọc nhầm thành
 * authorization thật.
 */
export default async function ReviewPage({ params }: PageProps<"/jobs/[jobId]/review">) {
  const { jobId } = await params;
  const [review, validation] = await Promise.all([getReview(jobId), getValidation(jobId)]);

  if (!review.ok) {
    return (
      <>
        <PageHeader title="Review" subtitle={jobId} />
        <JobTabs jobId={jobId} active="Review" />
        <ErrorState title="Không tải được trạng thái review" detail={review.error.detail} />
      </>
    );
  }

  // Backend chỉ có APPROVE/REJECT, không có "PENDING". Chưa có approval là khi
  // `approval` vắng mặt — đó là lúc reviewer phải quyết, nên panel phải hiện form.
  const approval = review.data.approval ?? null;
  const reportChecksum = validation.ok ? validation.data.report.report_checksum : null;

  return (
    <>
      <PageHeader
        title="Review"
        subtitle={
          approval
            ? `reviewer: ${approval.reviewer_id} · ${approval.decided_at}`
            : "chưa có quyết định nào"
        }
      />
      <JobTabs jobId={jobId} active="Review" />

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        {/* Left: review lifecycle panel */}
        <ReviewLifecyclePanel jobId={jobId} review={review.data} />

        {/* Right: checksum cross-reference */}
        <aside className="flex flex-col gap-4">
          <Panel>
            <div className="p-4">
              <PanelHeader title="Ràng buộc approval" />
              {approval ? (
                <>
                  <ul className="mt-2 flex flex-col gap-2 text-xs">
                    <li>
                      <Checksum value={approval.candidate_checksum} label="candidate" />
                    </li>
                    <li>
                      <Checksum value={approval.validation_report_checksum} label="validation report" />
                    </li>
                    <li>
                      <Checksum value={reportChecksum} label="validation thực tế của job" />
                    </li>
                    <li>
                      <Checksum value={approval.record_checksum} label="approval record" />
                    </li>
                  </ul>
                  {reportChecksum && reportChecksum !== approval.validation_report_checksum && (
                    <div className="mt-3">
                      <Banner tone="danger" title="Checksum mismatch" testId="checksum-mismatch">
                        Approval trỏ tới validation report khác với report hiện có. Quyết định này
                        không áp dụng cho revision đang xem.
                      </Banner>
                    </div>
                  )}
                </>
              ) : (
                <p className="mt-2 text-xs text-slate-500">
                  Chưa có approval record. Checksum ràng buộc chỉ hiện sau khi có quyết định.
                </p>
              )}
            </div>
          </Panel>

          <Panel>
            <div className="p-4">
              <PanelHeader title="Warnings đã chấp nhận" />
              {!approval || approval.accepted_warning_ids.length === 0 ? (
                <p className="text-xs text-slate-600">Không có.</p>
              ) : (
                <ul className="list-inside list-disc space-y-0.5 text-xs text-slate-400">
                  {approval.accepted_warning_ids.map((id) => (
                    <li key={id} className="font-mono">
                      {id}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Panel>

          <Panel>
            <div className="p-4">
              <PanelHeader title="Bước tiếp theo" />
              <p className="text-xs text-slate-500">
                Sau khi Approve → qua tab{" "}
                <span className="text-sky-400">Release</span> để seal exact candidate thành
                ReleaseManifest (PRODUCT-11).
              </p>
            </div>
          </Panel>
        </aside>
      </div>
    </>
  );
}
