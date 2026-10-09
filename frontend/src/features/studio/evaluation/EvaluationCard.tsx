"use client";

import { Download } from "lucide-react";
import { useEffect, useState } from "react";

import { ErrorFeedback } from "@/components/studio/feedback";
import { Badge, Button, buttonVariants, Notice } from "@/components/studio/primitives";
import { evaluationReportUrl, getJobEvaluation, type EvaluationGroup, type EvaluationMetric, type JobEvaluation } from "@/lib/api/studio";
import { errorMessage } from "@/lib/ui-error";

const VERDICT = { ok: { label: "Đạt", tone: "sage" }, warn: { label: "Cần xem", tone: "ochre" }, fail: { label: "Không đạt", tone: "rust" } } as const;
const GROUP_STATUS = { pending: "Chưa có kết quả", unavailable: "Chưa đo được" } as const;

/** Tải bảng đánh giá của job; `refreshKey` đổi (vd revision mới) thì tải lại. */
function useEvaluation(jobId: string, refreshKey: string) {
  const [state, setState] = useState<{ data: JobEvaluation | null; error: string | null }>({ data: null, error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getJobEvaluation(jobId, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setState({ data, error: null }); })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setState({ data: null, error: errorMessage(cause) }); });
    return () => controller.abort();
  }, [jobId, refreshKey, attempt]);
  return { ...state, retry: () => setAttempt((value) => value + 1) };
}

function MetricRow({ metric }: { metric: EvaluationMetric }) {
  const verdict = metric.verdict ? VERDICT[metric.verdict] : null;
  return (
    <div className="border-t border-line py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <dt className="text-ink-muted">{metric.label}</dt>
        <dd className={`text-sm font-semibold ${metric.value === null ? "font-normal text-ink-subtle" : "text-ink"}`}>
          {metric.display}
          {verdict && <Badge tone={verdict.tone} className="ml-2 align-middle">{verdict.label}</Badge>}
        </dd>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-ink-subtle">
        {metric.meaning}
        {metric.verdict && metric.threshold ? ` Ngưỡng: ${metric.threshold}.` : ""}
      </p>
      {metric.reference && (
        <p className="mt-1 text-xs text-ink-muted">
          {metric.reference}
        </p>
      )}
    </div>
  );
}

function GroupBody({ group }: { group: EvaluationGroup }) {
  if (group.status !== "measured") {
    return <p className="text-sm text-ink-muted">{GROUP_STATUS[group.status]}. {group.note}</p>;
  }
  return (
    <>
      {group.note && <p className="mb-1 text-xs text-ink-subtle">{group.note}</p>}
      <dl>{group.metrics.map((metric) => <MetricRow key={metric.key} metric={metric} />)}</dl>
    </>
  );
}

/** Chỉ số của một bước, hiện cạnh kết quả của chính bước đó. Bước không có nhóm chỉ số thì không vẽ gì. */
export function StageMetrics({ jobId, groupId }: { jobId: string; groupId: string }) {
  const { data, error, retry } = useEvaluation(jobId, groupId);
  if (error) return <ErrorFeedback message={`Không tải được chỉ số: ${error}`} retry={retry} />;
  if (!data) return <p role="status" className="text-sm text-ink-muted">Đang tải chỉ số…</p>;
  const group = data.groups.find((item) => item.group_id === groupId);
  if (!group) return null;
  return (
    <section aria-label="Chỉ số của giai đoạn">
      <h2 className="font-bold">Chỉ số của giai đoạn</h2>
      <p className="mt-1 mb-2 text-xs text-ink-subtle">Đo từ chính dữ liệu của scene, không so với ground truth.</p>
      <GroupBody group={group} />
    </section>
  );
}

/** Bảng đánh giá tổng hợp của scene trước khi duyệt, kèm nút tải báo cáo. */
export function EvaluationCard({ jobId, revision }: { jobId: string; revision: string }) {
  const { data, error, retry } = useEvaluation(jobId, revision);

  function downloadJson() {
    if (!data) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `evaluation-${data.job_id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const hasWarnings = Boolean(
    data?.groups.some((group) =>
      group.metrics.some((metric) => metric.verdict === "warn" || metric.verdict === "fail")
    )
  );

  return (
    <section aria-labelledby="evaluation-heading" className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="evaluation-heading" className="text-lg font-bold tracking-tight">Bảng đánh giá</h3>
          <p className="mt-1 max-w-2xl text-sm text-ink-muted">
            Chỉ số tự kiểm của từng bước, đo từ chính dữ liệu của scene. Scene dựng từ dataset có ground truth có thêm mục so với dữ liệu đối chứng. Nhãn Đạt/Cần xem chỉ có ở chỉ số đã có ngưỡng; các chỉ số còn lại để bạn tự đánh giá.
          </p>
        </div>
        {data && (
          <div className="flex shrink-0 flex-wrap gap-2">
            <a href={evaluationReportUrl(jobId)} download className={buttonVariants({ variant: "secondary", size: "sm" })}><Download aria-hidden /> Báo cáo (.md)</a>
            <Button variant="secondary" size="sm" onClick={downloadJson}><Download aria-hidden /> Dữ liệu (.json)</Button>
          </div>
        )}
      </div>
      {error && <ErrorFeedback className="mt-4" message={`Không tải được bảng đánh giá: ${error}`} retry={retry} />}
      {!data && !error && <p role="status" className="mt-4 text-sm text-ink-muted">Đang tính bảng đánh giá…</p>}
      {data && data.summary.length > 0 && (
        <Notice tone={hasWarnings ? "ochre" : "neutral"} className="mt-4">
          <div className="space-y-1">
            {data.summary.map((line, idx) => (
              <p key={idx}>{line}</p>
            ))}
          </div>
        </Notice>
      )}
      {data && (
        <div className="mt-4 grid gap-x-8 gap-y-6 md:grid-cols-2">
          {data.groups.map((group) => (
            <div key={group.group_id}>
              <h4 className="label-tech mb-2 text-ink-muted">{group.title}</h4>
              <GroupBody group={group} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
