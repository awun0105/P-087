/**
 * Trạng thái dùng chung: lỗi, rỗng, đang tải, và badge trạng thái.
 *
 * Chúng tồn tại để mọi màn hình hiện lỗi backend theo cùng một cách. PRODUCT-05
 * yêu cầu "UI reflects backend state and explicit errors" — một màn hình trắng
 * khi API lỗi là vi phạm, không phải chi tiết trình bày.
 */

import type { ReactNode } from "react";

import { CopyButton } from "@/components/ui/copy-button";
import type { JobStatus, PrivacyResult } from "@/lib/contracts/api";

export function ErrorState({ title, detail }: { title: string; detail: string }) {
  return (
    <section
      role="alert"
      data-testid="error-state"
      className="rounded-lg border border-rose-800 bg-rose-950/40 p-4 text-sm text-rose-200"
    >
      <h2 className="mb-1 font-semibold">{title}</h2>
      <p className="font-mono text-xs whitespace-pre-wrap">{detail}</p>
    </section>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <p
      data-testid="empty-state"
      className="rounded-lg border border-dashed border-slate-700 p-4 text-sm text-slate-400"
    >
      {message}
    </p>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <p data-testid="loading-state" className="p-4 text-sm text-slate-400">
      {label}
    </p>
  );
}

const JOB_STATUS_STYLES: Record<JobStatus, string> = {
  QUEUED: "bg-slate-700 text-slate-100",
  RUNNING: "bg-sky-700 text-sky-50",
  SUCCEEDED: "bg-emerald-700 text-emerald-50",
  FAILED: "bg-rose-700 text-rose-50",
  CANCELLED: "bg-slate-600 text-slate-200",
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      data-testid="job-status"
      className={`rounded px-2 py-0.5 text-xs font-medium ${JOB_STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  );
}

const PRIVACY_STYLES: Record<PrivacyResult, string> = {
  VERIFIED_ANONYMIZED: "bg-emerald-900 text-emerald-200",
  PRELIMINARY_SCREENED: "bg-amber-900 text-amber-200",
  QUARANTINED: "bg-rose-900 text-rose-200",
};

export function PrivacyBadge({ result, dispatchAllowed }: { result: PrivacyResult; dispatchAllowed: boolean }) {
  return (
    <span
      data-testid="privacy-badge"
      className={`rounded px-2 py-0.5 text-xs font-medium ${PRIVACY_STYLES[result]}`}
    >
      {result}
      {dispatchAllowed ? " · cho phép dispatch" : " · chặn dispatch"}
    </span>
  );
}

/** Rút gọn checksum để hiện trong bảng mà không phá layout. */
export function Checksum({ value, label }: { value: string | null; label?: string }): ReactNode {
  if (!value) {
    return <span className="text-slate-500">—</span>;
  }
  return (
    <span className="inline-flex items-center gap-1 font-mono text-xs text-slate-400" title={value}>
      {label ? `${label}: ` : ""}
      {value.slice(0, 18)}…
      <CopyButton value={value} />
    </span>
  );
}
