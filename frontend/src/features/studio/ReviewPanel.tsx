"use client";

import { notifySuccess } from "@/components/studio/feedback";

import { errorMessage } from "@/lib/ui-error";

import { Ban, Check, Circle, Download, Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, Notice, buttonVariants } from "@/components/studio/primitives";
import { TraceList } from "@/features/studio/TraceList";
import { useAuth } from "@/features/studio/AuthProvider";
import { canDecideReview } from "@/lib/api/auth";
import {
  getReviewState,
  releaseDownloadUrl,
  retryReleaseSeal,
  submitReviewDecision,
  type ReviewStateView,
  type RevisionStatus,
} from "@/lib/api/studio";
import { cn } from "@/lib/cn";

const STATUS_LABEL: Record<RevisionStatus, { label: string; tone: "neutral" | "ochre" | "sage" | "rust" | "ember" }> = {
  DRAFT: { label: "Bản nháp", tone: "neutral" },
  PROCESSING: { label: "Đang xử lý", tone: "ember" },
  CANDIDATE_READY: { label: "Có gói — chờ validation", tone: "ochre" },
  VALIDATING: { label: "Đang validation", tone: "ember" },
  READY_FOR_REVIEW: { label: "Đạt kiểm tra — chờ duyệt", tone: "ochre" },
  APPROVED: { label: "Đã duyệt — chưa phát hành", tone: "ochre" },
  REJECTED: { label: "Bị từ chối", tone: "rust" },
  RELEASED: { label: "Đã phát hành", tone: "sage" },
};

/**
 * Kiểm tra & duyệt (PRODUCT-10/11) cho revision hiện tại. Trạng thái do backend suy từ artifact;
 * panel chỉ gửi quyết định kèm checksum gói/báo cáo đang hiển thị để backend phát hiện màn hình cũ.
 * Duyệt xong hệ thống tự phát hành (không có bước duyệt thứ hai).
 */
export function ReviewPanel({ jobId, sceneRevision, refreshToken = 0, onState }: {
  jobId: string;
  sceneRevision: string;
  refreshToken?: number;
  /** Màn cha (tab Kiểm tra & duyệt) dùng lại trạng thái panel đã tải để vẽ báo cáo chi tiết, không gọi API lần hai. */
  onState?: (state: ReviewStateView | null) => void;
}) {
  const { me } = useAuth();
  const [state, setState] = useState<ReviewStateView | null>(null);
  const [loadedRevision, setLoadedRevision] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getReviewState(jobId, controller.signal).then(
      (value) => {
        if (controller.signal.aborted) return;
        setState(value);
        setLoadedRevision(sceneRevision);
        setError(null);
        setAccepted([]);
        setConfirming(false);
      },
      (cause: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(cause, "Không đọc được trạng thái duyệt"));
      },
    );
    return () => controller.abort();
  }, [jobId, sceneRevision, reload, refreshToken]);

  // Chỉ đưa ra ngoài trạng thái của đúng revision đang xem; đang tải lại thì báo null để màn cha ẩn báo cáo cũ.
  const current = state && loadedRevision === sceneRevision ? state : null;
  useEffect(() => {
    onState?.(current);
  }, [current, onState]);

  async function run(action: () => Promise<ReviewStateView>) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setState(next);
      notifySuccess(next.record.status === "RELEASED" ? "Đã phát hành gói được duyệt." : next.record.status === "REJECTED" ? "Đã gửi yêu cầu sửa." : "Đã ghi nhận thao tác duyệt; xem trạng thái mới trong panel.");
      setConfirming(false);
    } catch (cause: unknown) {
      setError(errorMessage(cause, "Thao tác thất bại"));
    } finally {
      setBusy(false);
    }
  }

  if (!state || loadedRevision !== sceneRevision) {
    return error ? <Notice tone="rust" className="m-4">{error} <Button size="sm" variant="secondary" onClick={() => { setError(null); setReload((value) => value + 1); }}>Thử lại</Button></Notice> : <p role="status" className="p-4 text-sm text-ink-muted">Đang đọc trạng thái duyệt…</p>;
  }
  const { record, validation } = state;
  if (record.scene_revision !== sceneRevision) {
    return <Notice tone="ochre" className="m-4">Trạng thái duyệt đang thuộc {record.scene_revision}; scene hiện tại là {sceneRevision}. Tải lại scene trước khi quyết định.</Notice>;
  }
  const reviewer = canDecideReview(me);
  const status = STATUS_LABEL[record.status];
  const trustedValidation =
    state.isaac_runtime_proof === true &&
    validation?.overall_result === "PASS" &&
    validation.candidate_checksum === record.candidate_checksum &&
    validation.report_checksum === record.validation_report_checksum &&
    record.candidate_checksum !== null &&
    record.validation_report_checksum !== null;
  const canReview = record.status === "READY_FOR_REVIEW" && trustedValidation && state.blockers.length === 0;
  const decision = (value: "APPROVE" | "REJECT") =>
    run(() =>
      submitReviewDecision(jobId, {
        decision: value,
        candidate_checksum: record.candidate_checksum!,
        validation_report_checksum: record.validation_report_checksum!,
        accepted_warning_ids: value === "APPROVE" ? accepted : [],
        reason: value === "REJECT" ? reason : undefined,
      }),
    );
  const allAccepted = state.warning_ids.every((id) => accepted.includes(id));
  return (
    <section className="space-y-3 p-5 text-sm" aria-label="Kiểm tra và duyệt">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          <ShieldCheck className="size-4" aria-hidden /> Kiểm tra & duyệt
        </p>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>
      <ReviewSteps state={state} />
      {state.blockers.length > 0 && (
        <Notice tone="ochre">
          <p className="font-semibold text-ink">Chưa đủ điều kiện duyệt</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {state.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
          </ul>
        </Notice>
      )}
      {state.release_seal_error && <Notice tone="ochre">{state.release_seal_error}</Notice>}
      {validation && (
        <p className="text-ink-muted">
          Validation <span className="font-medium text-ink">{validation.overall_result}</span> · {validation.validator_version} ·{" "}
          {validation.checks.length} check · {validation.path_results.length} cặp Start–Goal. Chi tiết và bằng chứng ở thẻ Báo cáo validation.
        </p>
      )}
      {validation && state.isaac_runtime_proof !== true && (
        <Notice tone="ochre">Báo cáo này chưa gắn với validation run worker và runtime manifest đã xác minh; chỉ dùng để xem thông tin.</Notice>
      )}
      {record.status === "READY_FOR_REVIEW" && !canReview && state.blockers.length === 0 && (
        <Notice tone="rust">Backend chưa cung cấp eligibility hợp lệ cho revision này. Tải lại trạng thái trước khi quyết định.</Notice>
      )}
      {canReview && !reviewer && (
        <Notice tone="ochre">
          {me?.auth_required === false
            ? "Deployment chưa bật đăng nhập nên không thể duyệt. Đặt AUTH_REQUIRED=true và đăng nhập bằng tài khoản Reviewer để duyệt hoặc yêu cầu sửa."
            : "Chỉ Reviewer có quyền phê duyệt hoặc yêu cầu sửa. Bạn có thể xem báo cáo và bằng chứng của revision này."}
        </Notice>
      )}
      {canReview && reviewer && (
        <div className="space-y-2">
          {state.warning_ids.length > 0 && (
            <fieldset className="space-y-1">
              <legend className="text-ink-muted">Chấp nhận từng cảnh báo trước khi duyệt:</legend>
              {state.warning_ids.map((id) => {
                const check = validation?.checks.find((item) => item.check_id === id);
                const pathId = id.startsWith("path:") ? id.slice("path:".length) : null;
                const path = pathId ? validation?.path_results.find((item) => item.pair_id === pathId) : undefined;
                const message = check?.message ?? path?.message;
                const evidenceCount = check?.evidence_refs.length ?? path?.evidence_refs.length ?? 0;
                const describedBy = check || path ? `warning-${id.replaceAll(":", "-")}` : undefined;
                return (
                  <div key={id}>
                    <label className="flex items-center gap-1.5">
                      <input
                        type="checkbox"
                        checked={accepted.includes(id)}
                        aria-describedby={describedBy}
                        onChange={(event) =>
                          setAccepted(event.target.checked ? [...accepted, id] : accepted.filter((value) => value !== id))
                        }
                      />
                      {id}
                    </label>
                    {(check || path) && (
                      <p id={describedBy} className="ml-5 text-xs text-ink-muted">
                        {message ?? (path ? `Kết quả ${path.result}.` : "Check không kèm thông điệp.")} · {evidenceCount > 0 ? `${evidenceCount} bằng chứng trong báo cáo` : "không kèm bằng chứng"}
                      </p>
                    )}
                  </div>
                );
              })}
            </fieldset>
          )}
          {confirming ? (
            <div className="space-y-1.5 rounded-md border border-line p-2">
              <p>
                Phê duyệt gói <code>{record.candidate_checksum?.slice(7, 19)}</code> của {record.scene_revision}? Hệ thống
                sẽ phát hành đúng gói này ngay sau đó.
              </p>
              <div className="flex gap-1.5">
                <Button size="sm" disabled={busy} onClick={() => decision("APPROVE")}>
                  {busy && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />} Xác nhận phê duyệt
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                  Huỷ
                </Button>
              </div>
            </div>
          ) : (
            <Button size="sm" disabled={busy || !allAccepted} onClick={() => setConfirming(true)}>
              Phê duyệt để phát hành
            </Button>
          )}
          <label className="flex flex-col gap-1 text-ink-muted">
            Lý do yêu cầu sửa
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={2}
              className="rounded-md border border-line-strong bg-paper px-2 py-1 text-sm text-ink"
            />
          </label>
          <Button size="sm" variant="danger" disabled={busy || !reason.trim()} onClick={() => decision("REJECT")}>
            Yêu cầu sửa
          </Button>
        </div>
      )}
      {state.approval && (
        <p className="text-ink-muted">
          {state.approval.decision === "APPROVE" ? "Duyệt" : "Từ chối"} bởi <strong className="font-semibold text-ink">{state.reviewer_name ?? state.approval.reviewer_id}</strong> lúc{" "}
          {new Date(state.approval.decided_at).toLocaleString("vi-VN")}
          {state.approval.reason && <span className="block text-ink">Lý do: {state.approval.reason}</span>}
        </p>
      )}
      {state.approval && (
        <details className="rounded-md border border-line px-2 py-1.5">
          <summary className="cursor-pointer text-ink-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-ember">Nguồn kết quả của quyết định</summary>
          <div className="mt-2">
            <TraceList
              rows={[
                { label: "Checksum gói đã quyết định", value: state.approval.candidate_checksum },
                { label: "Checksum báo cáo đã xem", value: state.approval.validation_report_checksum },
                { label: "Checksum bản ghi duyệt", value: state.approval.record_checksum },
              ]}
            />
          </div>
        </details>
      )}
      {record.status === "APPROVED" && reviewer && (
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => run(() => retryReleaseSeal(jobId))}>
          Thử lại phát hành
        </Button>
      )}
      {record.status === "RELEASED" && state.release && (
        <>
          <p className="text-ink-muted">
            Phát hành {new Date(state.release.release_timestamp).toLocaleString("vi-VN")} · manifest{" "}
            <code>{state.release.release_manifest_checksum.slice(7, 19)}</code>
          </p>
          <a href={releaseDownloadUrl(jobId)} className={cn(buttonVariants({ size: "sm" }), "w-full")}>
            <Download aria-hidden /> Tải bản phát hành (.zip)
          </a>
        </>
      )}
      {record.status === "REJECTED" && <p className="text-ink-muted">Sửa scene (tạo revision mới) rồi tạo gói và kiểm tra lại.</p>}
      {error && <p className="text-rust">{error}</p>}
    </section>
  );
}

type StepState = "done" | "next" | "unavailable" | "blocked";

/**
 * Bốn chặng gói → validation Isaac → duyệt → phát hành. Backend là thẩm quyền về eligibility;
 * panel chỉ hiển thị trusted proof, blockers và status đã được xác minh.
 */
function ReviewSteps({ state }: { state: ReviewStateView }) {
  const status = state.record.status;
  const hasPackage = state.record.candidate_checksum !== null;
  const validated =
    state.isaac_runtime_proof === true &&
    state.validation?.overall_result === "PASS" &&
    state.validation.candidate_checksum === state.record.candidate_checksum &&
    state.validation.report_checksum === state.record.validation_report_checksum &&
    state.record.candidate_checksum !== null &&
    state.record.validation_report_checksum !== null &&
    state.blockers.length === 0;
  const decided = status === "APPROVED" || status === "REJECTED" || status === "RELEASED";
  const steps: { label: string; state: StepState; note: string }[] = [
    { label: "Gói mô phỏng + preflight", state: hasPackage ? "done" : "next", note: hasPackage ? "Có gói cho revision này" : "Tạo gói ở mục Gói mô phỏng" },
    {
      label: "Validation Isaac Sim",
      state: validated ? "done" : state.blockers.length > 0 || state.validation ? "blocked" : hasPackage ? "unavailable" : "blocked",
      note: state.validation
        ? validated
          ? `Kết quả ${state.validation.overall_result} từ run worker đã xác minh`
          : "Báo cáo chưa đủ điều kiện làm validation proof"
        : state.blockers.length > 0
          ? "Có lý do chặn, xem bên dưới"
          : "Chưa khả dụng: chưa có validation run được chọn",
    },
    {
      label: "Người duyệt quyết định",
      state: decided ? "done" : validated && status === "READY_FOR_REVIEW" ? "next" : state.blockers.length > 0 ? "blocked" : hasPackage ? "unavailable" : "blocked",
      note: decided ? (status === "REJECTED" ? "Bị từ chối" : "Đã duyệt") : validated ? "Chờ Reviewer xem xét" : "Chỉ mở khi đủ validation proof",
    },
    {
      label: "Phát hành",
      state: status === "RELEASED" ? "done" : status === "APPROVED" ? "next" : state.blockers.length > 0 ? "blocked" : hasPackage ? "unavailable" : "blocked",
      note: status === "RELEASED" ? "Đã có bản phát hành" : validated ? "Tự đóng gói ngay sau khi được duyệt" : "Chưa thể phát hành",
    },
  ];
  const icon = (value: StepState) =>
    value === "done" ? (
      <Check className="size-3.5 text-sage" aria-hidden />
    ) : value === "unavailable" ? (
      <Ban className="size-3.5 text-ink-subtle" aria-hidden />
    ) : (
      <Circle className={cn("size-3.5", value === "next" ? "text-ember" : "text-ink-subtle")} aria-hidden />
    );
  return (
    <ol className="space-y-1.5" aria-label="Các chặng duyệt">
      {steps.map((step) => (
        <li key={step.label} className="flex items-start gap-2">
          <span className="mt-0.5">{icon(step.state)}</span>
          <span>
            <span className={cn("font-medium", step.state === "unavailable" ? "text-ink-muted" : "text-ink")}>{step.label}</span>
            <span className="block text-ink-subtle">{step.note}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
