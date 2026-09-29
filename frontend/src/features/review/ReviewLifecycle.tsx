/**
 * ReviewLifecyclePanel — submit/approve/reject với fake state machine (PRODUCT-10).
 *
 * Fake endpoint gọi /api/v1/jobs/{jobId}/review/{action} (POST).
 * Khi PRODUCT-10 backend được implement, client này sẽ hoạt động ngay
 * vì contract đã định sẵn.
 *
 * Cờ `synthetic_authorization` phải luôn đi kèm khi dùng fake reviewer id.
 */

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Banner } from "@/components/ui/banner";
import { Panel, PanelHeader } from "@/components/ui/panel";
import type { ReviewState } from "@/lib/contracts/api";

type ReviewAction = "submit" | "approve" | "reject";

async function callReviewAction(
  jobId: string,
  action: ReviewAction,
  payload: Record<string, unknown>,
): Promise<{ note?: string }> {
  const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/review/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<{ note?: string }>;
}

export function ReviewLifecyclePanel({
  jobId,
  review,
  enabled = false,
}: {
  jobId: string;
  review: ReviewState;
  enabled?: boolean;
}) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<ReviewAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Backend không có decision "PENDING": `approval` vắng mặt nghĩa là chưa có quyết
  // định, và đó mới là lúc form Approve/Reject phải hiện. Bản cũ so sánh với "PENDING"
  // nên với decision thật (APPROVE/REJECT) `isFinal` luôn true và form không bao giờ hiện.
  const isFinal = review.approval !== undefined;
  const decision = review.approval?.decision;

  async function run(action: ReviewAction, extra?: Record<string, unknown>) {
    if (!enabled) return;
    if (action === "reject" && !reason.trim()) {
      setError("Lý do từ chối không được để trống.");
      return;
    }
    setBusy(action);
    setError(null);
    setSuccess(null);
    try {
      await callReviewAction(jobId, action, {
        reviewer_id: "reviewer-mock-001",
        reason: reason.trim() || null,
        candidate_checksum: review.approval?.candidate_checksum ?? null,
        validation_report_checksum: review.approval?.validation_report_checksum ?? null,
        ...extra,
      });
      setSuccess(`Action "${action}" gửi thành công.`);
      setReason("");
      setTimeout(() => router.refresh(), 600);
    } catch (cause) {
      setError(
        cause instanceof ApiError ? `${cause.status}: ${cause.detail}` : String(cause),
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {!enabled && <Banner tone="warn" title="Review chỉ đọc">Authorization và lưu quyết định review chưa được nối backend.</Banner>}
      {/* Mock warning */}
      {review.synthetic_authorization && (
        <Banner
          tone="warn"
          title="⚠ Mock review — chưa phải authorization thật"
          testId="synthetic-authorization"
        >
          {review.note}
        </Banner>
      )}

      {/* Review state machine visual */}
      <Panel>
        <div className="p-4">
          <PanelHeader title="Trạng thái review" />
          <div className="mt-2">
            <ReviewStateMachine current={decision ?? null} />
          </div>
        </div>
      </Panel>

      {/* Decision card — chỉ có nội dung khi đã có approval record. */}
      <Panel>
        <div className="p-4">
          <PanelHeader title="Quyết định" />
          {review.approval ? (
            <>
              <div className="mt-2 flex items-center gap-3">
                <DecisionBadge decision={decision ?? null} />
                <span className="text-xs text-slate-500">{review.approval.decided_at}</span>
              </div>
              {review.approval.reason && (
                <p className="mt-2 text-xs text-slate-300">{review.approval.reason}</p>
              )}
            </>
          ) : (
            <p className="mt-2 text-xs text-slate-500">
              Chưa có quyết định. Backend chỉ phát hành approval khi đã APPROVE hoặc REJECT.
            </p>
          )}
        </div>
      </Panel>

      {/* Actions — only if not final */}
      {!isFinal && (
        <Panel>
          <div className="p-4">
            <PanelHeader title="Hành động" />

            {/* Reason input */}
            <div className="mt-2 mb-3">
              <label className="mb-1 block text-[11px] font-medium text-slate-500">
                Lý do (bắt buộc khi từ chối)
              </label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={2}
                placeholder="Mô tả lý do quyết định…"
                className="w-full resize-none rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-sky-600 focus:outline-none"
                aria-label="Lý do review"
              />
            </div>

            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                busy={busy === "approve"}
                disabled={!enabled || busy !== null}
                onClick={() => void run("approve", { accepted_warning_ids: [] })}
                className="flex-1"
              >
                Approve
              </Button>
              <Button
                variant="danger"
                size="sm"
                busy={busy === "reject"}
                disabled={!enabled || busy !== null || !reason.trim()}
                onClick={() => void run("reject")}
                className="flex-1"
              >
                Reject
              </Button>
            </div>

            <p className="mt-2 text-[10px] text-slate-600">
              Endpoint <span className="font-mono">/review/approve</span> và{" "}
              <span className="font-mono">/review/reject</span> là fake stub — trả 200 nhưng không
              persist vào backend. Decision sẽ reset khi refresh. Payload được gửi đúng contract.
            </p>
          </div>
        </Panel>
      )}

      {/* Checksums binding */}
      <Panel>
        <div className="p-4 text-xs">
          <PanelHeader title="Ràng buộc checksum" />
          <ul className="mt-2 space-y-1 font-mono text-[10px] text-slate-500">
            <li>candidate: {review.approval?.candidate_checksum.slice(0, 26)}…</li>
            <li>validation: {review.approval?.validation_report_checksum.slice(0, 26) ?? "—"}…</li>
            <li>record: {review.approval?.record_checksum.slice(0, 26)}…</li>
          </ul>
          <p className="mt-2 text-[10px] text-slate-700">
            Approve chỉ seal exact candidate đã validate. Edit sau validation → DRAFT mới.
          </p>
        </div>
      </Panel>

      {/* Feedback */}
      {error && (
        <p role="alert" className="rounded-xl bg-rose-950/60 p-3 text-xs text-rose-300">
          {error}
        </p>
      )}
      {success && (
        <p className="rounded-xl bg-emerald-950/60 p-3 text-xs text-emerald-300">{success}</p>
      )}
    </div>
  );
}

function DecisionBadge({ decision }: { decision: string | null }) {
  const tone = decision === "APPROVE" ? "ok" : decision === "REJECT" ? "danger" : "default";
  return <Badge tone={tone}>{decision ?? "CHƯA QUYẾT"}</Badge>;
}

/**
 * `PENDING` ở đây là nhãn hiển thị cho "chưa có approval", **không** phải giá trị
 * `ApprovalDecision` của backend — backend chỉ có APPROVE/REJECT.
 */
function ReviewStateMachine({ current }: { current: string | null }) {
  const states = [
    { id: "PENDING", label: "Chờ review" },
    { id: "APPROVE", label: "Approved" },
    { id: "REJECT", label: "Rejected" },
  ];

  return (
    <div className="flex flex-wrap items-center gap-2">
      {states.map((state, idx) => {
        const isActive =
          state.id === current ||
          (current !== "APPROVE" && current !== "REJECT" && state.id === "PENDING");
        return (
          <div key={state.id} className="flex items-center gap-2">
            {idx > 0 && <span className="text-xs text-slate-700">→</span>}
            <span
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium ${
                isActive
                  ? state.id === "APPROVE"
                    ? "border-emerald-800 bg-emerald-900/50 text-emerald-300"
                    : state.id === "REJECT"
                      ? "border-rose-800 bg-rose-900/50 text-rose-300"
                      : "border-sky-800 bg-sky-900/50 text-sky-300"
                  : "border-slate-800 bg-slate-900 text-slate-600"
              }`}
            >
              {state.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
