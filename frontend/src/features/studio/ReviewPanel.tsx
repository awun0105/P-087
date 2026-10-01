"use client";

import { Ban, Check, CheckCircle2, Circle, Download, Loader2, ShieldCheck, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, Notice, buttonVariants } from "@/components/studio/primitives";
import { useAuth } from "@/features/studio/AuthProvider";
import { isReviewer } from "@/lib/api/auth";
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
export function ReviewPanel({ jobId, sceneRevision }: { jobId: string; sceneRevision: string }) {
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
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Không đọc được trạng thái duyệt");
      },
    );
    return () => controller.abort();
  }, [jobId, sceneRevision, reload]);

  async function run(action: () => Promise<ReviewStateView>) {
    setBusy(true);
    setError(null);
    try {
      setState(await action());
      setConfirming(false);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Thao tác thất bại");
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
  const reviewer = isReviewer(me);
  const status = STATUS_LABEL[record.status];
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
      {/* Thiếu gói/validation đã hiện ở các chặng; lý do chặn chỉ thêm khi đã có báo cáo (vd. FAIL). */}
      {state.validation && state.blockers.map((blocker) => (
        <p key={blocker} className="text-ink-muted">
          {blocker}
        </p>
      ))}
      {validation && (
        <div className="space-y-1">
          <p className="text-ink-muted">
            Validation {validation.overall_result} · {validation.validator_version}
          </p>
          <ul className="space-y-0.5">
            {validation.checks.map((check) => (
              <li key={check.check_id} className="flex items-start gap-1.5">
                {check.result === "PASS" ? (
                  <CheckCircle2 className="mt-px size-3.5 shrink-0 text-sage" aria-label="Đạt" />
                ) : (
                  <XCircle className="mt-px size-3.5 shrink-0 text-rust" aria-label="Không đạt" />
                )}
                <span>
                  {check.check_id}
                  {check.message && <span className="text-ink-subtle"> · {check.message}</span>}
                </span>
              </li>
            ))}
            {validation.path_results.map((path) => (
              <li key={path.pair_id} className="text-ink-muted">
                Start–Goal {path.pair_id}: <span className="font-medium text-ink">{path.result}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {record.status === "READY_FOR_REVIEW" && !reviewer && <Notice tone="ochre">Chỉ Reviewer có quyền phê duyệt hoặc yêu cầu sửa. Bạn có thể xem báo cáo và bằng chứng của revision này.</Notice>}
      {record.status === "READY_FOR_REVIEW" && reviewer && (
        <div className="space-y-2">
          {state.warning_ids.length > 0 && (
            <fieldset className="space-y-1">
              <legend className="text-ink-muted">Chấp nhận từng cảnh báo trước khi duyệt:</legend>
              {state.warning_ids.map((id) => (
                <label key={id} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={accepted.includes(id)}
                    onChange={(event) =>
                      setAccepted(event.target.checked ? [...accepted, id] : accepted.filter((value) => value !== id))
                    }
                  />
                  {id}
                </label>
              ))}
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
          {state.approval.decision === "APPROVE" ? "Duyệt" : "Từ chối"} bởi {state.approval.reviewer_id} lúc{" "}
          {new Date(state.approval.decided_at).toLocaleString("vi-VN")}
          {state.approval.reason && <span className="block text-ink">Lý do: {state.approval.reason}</span>}
        </p>
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
 * Bốn chặng gói → validation Isaac → duyệt → phát hành (S09–S12). Validation Isaac cần máy RTX và
 * simulation worker (SIM-06..09) chưa có trong repo: khi chưa có báo cáo, chặng này và các chặng
 * sau hiện "Chưa khả dụng" (PRODUCT.md Q2) thay vì giả như đang chờ.
 */
function ReviewSteps({ state }: { state: ReviewStateView }) {
  const status = state.record.status;
  const hasPackage = status !== "DRAFT" || state.validation !== null;
  const validated = state.validation?.overall_result === "PASS";
  const decided = status === "APPROVED" || status === "REJECTED" || status === "RELEASED";
  const steps: { label: string; state: StepState; note: string }[] = [
    { label: "Gói mô phỏng + preflight", state: hasPackage ? "done" : "next", note: hasPackage ? "Có gói cho revision này" : "Tạo gói ở khung bên cạnh" },
    {
      label: "Validation Isaac Sim",
      state: state.validation ? (validated ? "done" : "blocked") : hasPackage ? "unavailable" : "blocked",
      note: state.validation
        ? `Kết quả ${state.validation.overall_result}`
        : "Chưa khả dụng: cần máy RTX chạy Isaac Sim (SIM-06..09 chưa triển khai)",
    },
    {
      label: "Người duyệt quyết định",
      state: decided ? "done" : status === "READY_FOR_REVIEW" ? "next" : state.validation ? "blocked" : "unavailable",
      note: decided ? (status === "REJECTED" ? "Bị từ chối" : "Đã duyệt") : "Chỉ mở khi validation đạt",
    },
    {
      label: "Phát hành",
      state: status === "RELEASED" ? "done" : status === "APPROVED" ? "next" : state.validation ? "blocked" : "unavailable",
      note: status === "RELEASED" ? "Đã có bản phát hành" : "Tự đóng gói ngay sau khi được duyệt",
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
