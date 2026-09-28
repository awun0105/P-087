/**
 * ReleasePanel — UI để trigger release với fake endpoint (PRODUCT-11).
 *
 * Chỉ enable nút khi tất cả điều kiện release đã thoả:
 * - Job SUCCEEDED
 * - Approval = APPROVE
 * - Checksum khớp
 *
 * Backend sẽ kiểm lại; UI chỉ block sớm để đỡ bấm nhầm.
 */

"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import type { ApprovalRecord, JobStatus } from "@/lib/contracts/api";

export function ReleasePanel({
  jobId,
  approved,
  checksumMatch,
  approvalRecord,
  jobStatus,
  enabled = false,
}: {
  jobId: string;
  approved: boolean;
  checksumMatch: boolean;
  approvalRecord: ApprovalRecord | null;
  jobStatus: JobStatus;
  /** Chỉ bật khi backend đã có sealing thật và authorization, không theo fixture approval. */
  enabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [releaseResult, setReleaseResult] = useState<{
    release_id: string;
    release_checksum: string;
    released_at: string;
  } | null>(null);

  const canRelease = enabled && jobStatus === "SUCCEEDED" && approved && checksumMatch && !releaseResult;

  async function doRelease() {
    if (!canRelease || !approvalRecord) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/release`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approval_record_checksum: approvalRecord.record_checksum,
          candidate_checksum: approvalRecord.candidate_checksum,
          validation_report_checksum: approvalRecord.validation_report_checksum,
        }),
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
      const data = (await res.json()) as {
        release_id: string;
        release_checksum: string;
        released_at: string;
      };
      setReleaseResult(data);
    } catch (cause) {
      setError(
        cause instanceof ApiError ? `${cause.status}: ${cause.detail}` : String(cause),
      );
    } finally {
      setBusy(false);
    }
  }

  if (releaseResult) {
    return (
      <Panel className="border-emerald-800 bg-emerald-950/40 p-6">
        <div className="mb-4 text-3xl">🎉</div>
        <h2 className="mb-2 text-lg font-semibold text-emerald-300">Release thành công!</h2>
        <ul className="space-y-1 text-xs text-emerald-200/70">
          <li>
            <span className="text-emerald-500">release id:</span>{" "}
            <span className="font-mono">{releaseResult.release_id}</span>
          </li>
          <li>
            <span className="text-emerald-500">checksum:</span>{" "}
            <span className="font-mono">{releaseResult.release_checksum.slice(0, 26)}…</span>
          </li>
          <li>
            <span className="text-emerald-500">released at:</span>{" "}
            <span className="font-mono">{releaseResult.released_at}</span>
          </li>
        </ul>
        <p className="mt-3 text-[10px] text-emerald-700">
          ReleaseManifest đã seal exact candidate. Không thể undo.
        </p>
      </Panel>
    );
  }

  return (
    <Panel>
      <div className="p-6">
        <PanelHeader title="Seal & Release" />
        {!enabled && <p className="mt-2 text-sm text-amber-300">Read-only: backend chưa triển khai release sealing thật.</p>}
        <p className="mt-2 text-xs leading-relaxed text-slate-400">
          Nút <span className="font-medium text-white">Release</span> sẽ gọi backend để seal exact
          candidate đã validate + approved thành{" "}
          <span className="font-mono text-sky-400">ReleaseManifest</span>. Không rebuild — không
          thay đổi artifact sau approval.
        </p>

        {!canRelease && (
          <div className="mt-4 rounded-lg border border-amber-800 bg-amber-950/30 p-3 text-xs text-amber-300">
            {!approved && <p>• Chưa có approval (vào tab Review để approve).</p>}
            {approved && !checksumMatch && (
              <p>• Checksum candidate/validation không khớp approval record.</p>
            )}
            {jobStatus !== "SUCCEEDED" && <p>• Job chưa SUCCEEDED (hiện: {jobStatus}).</p>}
          </div>
        )}

        <Button
          variant="primary"
          size="md"
          busy={busy}
          disabled={!canRelease}
          onClick={() => void doRelease()}
          className="mt-4 w-full"
        >
          {busy ? "Đang seal…" : canRelease ? "⬆ Release candidate" : "Chưa đủ điều kiện release"}
        </Button>

        {error && (
          <p role="alert" className="mt-3 rounded-lg bg-rose-950/60 p-3 text-xs text-rose-300">
            {error}
          </p>
        )}
      </div>

      {/* Payload preview */}
      {approvalRecord && (
        <details className="border-t border-slate-800 p-4">
          <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-400">
            Xem payload sẽ gửi
          </summary>
          <pre className="mt-3 overflow-x-auto text-[10px] text-slate-600">
            {JSON.stringify(
              {
                approval_record_checksum: approvalRecord.record_checksum,
                candidate_checksum: approvalRecord.candidate_checksum,
                validation_report_checksum: approvalRecord.validation_report_checksum,
              },
              null,
              2,
            )}
          </pre>
        </details>
      )}
    </Panel>
  );
}
