import { JobTabs, PageHeader } from "@/components/shell";
import { Checksum, ErrorState } from "@/components/states";
import { getReview, getValidation } from "@/lib/api/endpoints";

/**
 * Màn hình mock review — bước cuối của luồng demo M1.
 *
 * Màn hình này cố ý **không** hiện chữ "APPROVED" trần. Approval ở M1 đến từ
 * fixture, nên cờ `synthetic_authorization` phải nằm cạnh quyết định; nếu không
 * thì mock review bị đọc thành authorization thật (PRODUCT-10 chưa làm).
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

  const { approval } = review.data;
  const reportChecksum = validation.ok ? validation.data.report.report_checksum : null;

  return (
    <>
      <PageHeader title="Review" subtitle={`reviewer ${approval.reviewer_id}`} />
      <JobTabs jobId={jobId} active="Review" />

      {review.data.synthetic_authorization && (
        <p
          data-testid="synthetic-authorization"
          className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200"
        >
          <strong>Đây là mock review, không phải authorization.</strong> {review.data.note}
        </p>
      )}

      <section className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 text-sm">
          <h2 className="mb-2 text-xs tracking-wide text-slate-400 uppercase">Quyết định</h2>
          <p className="text-lg font-semibold text-slate-100">{approval.decision}</p>
          <p className="mt-1 text-xs text-slate-400">lúc {approval.decided_at}</p>
          {approval.reason && <p className="mt-2 text-xs text-slate-300">{approval.reason}</p>}
          <p className="mt-2 text-xs text-slate-500">
            accepted warnings: {approval.accepted_warning_ids.length === 0 ? "không có" : approval.accepted_warning_ids.join(", ")}
          </p>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 text-sm">
          <h2 className="mb-2 text-xs tracking-wide text-slate-400 uppercase">Ràng buộc</h2>
          <ul className="flex flex-col gap-1">
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
              <Checksum value={approval.record_checksum} label="record" />
            </li>
          </ul>
          {reportChecksum && reportChecksum !== approval.validation_report_checksum && (
            <p data-testid="checksum-mismatch" className="mt-2 rounded bg-rose-950/60 p-2 text-xs text-rose-300">
              Approval trỏ tới một validation report khác với report hiện có của job. Quyết định này không
              áp dụng cho revision đang xem.
            </p>
          )}
        </div>
      </section>

      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900/60 p-4 text-sm">
        <h2 className="mb-2 text-xs tracking-wide text-slate-400 uppercase">Chưa làm ở M1</h2>
        <ul className="list-inside list-disc text-xs text-slate-400">
          <li>PRODUCT-10 — review lifecycle và authorization: chỉ Reviewer được approve/reject.</li>
          <li>PRODUCT-11 — seal exact candidate, không rebuild sau approval.</li>
        </ul>
        <p className="mt-2 text-xs text-slate-500">
          Nút approve/reject không được dựng ở đây: một nút như vậy ở thời điểm này sẽ là authorization giả.
        </p>
      </section>
    </>
  );
}
