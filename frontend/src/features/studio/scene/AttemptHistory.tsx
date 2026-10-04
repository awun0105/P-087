"use client";

import { useEffect, useState } from "react";
import { ErrorFeedback } from "@/components/studio/feedback";
import { listJobAttempts } from "@/lib/api/endpoints";
import type { JobAttempt } from "@/lib/contracts/api";
import { errorMessage } from "@/lib/ui-error";
import { stageMeta } from "@/features/studio/stages";

const LABEL: Record<string, string> = { QUEUED: "Chờ xử lý", RUNNING: "Đang chạy", SUCCEEDED: "Hoàn tất", FAILED: "Lỗi", CANCELLED: "Đã huỷ" };
export function AttemptHistory({ jobId, attempt, status }: { jobId: string; attempt: number; status: string }) {
  const [records, setRecords] = useState<JobAttempt[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    void listJobAttempts(jobId).then((result) => {
      if (!alive) return;
      if (result.ok) { setRecords(result.data.attempts); setError(null); }
      else setError(errorMessage(result.error));
    });
    return () => { alive = false; };
  }, [jobId, attempt, status, reload]);
  return <details className="rounded-xl border border-line bg-paper-raised p-4">
    <summary className="cursor-pointer font-medium">Lịch sử xử lý{records ? " · " + records.length + " bản ghi" : ""}</summary>
    <div className="mt-3">
      {error ? <ErrorFeedback message={error} retry={() => setReload((value) => value + 1)} /> : records === null ? <p role="status" className="text-sm text-ink-muted">Đang đọc lịch sử…</p> :
        records.length === 0 ? <p className="text-sm text-ink-muted">Chưa có bản ghi attempt.</p> :
          <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="text-ink-muted"><th className="p-2">Lần chạy</th><th className="p-2">Trạng thái</th><th className="p-2">Giai đoạn</th><th className="p-2">Ghi nhận</th></tr></thead><tbody>
            {[...records].reverse().map((record, index) => <tr key={String(record.attempt) + ":" + index} className="border-t border-line">
              <td className="p-2">{record.attempt}{record.job_manifest_checksum && <details className="mt-1 text-xs text-ink-muted"><summary className="cursor-pointer">Checksum bản ghi</summary><code className="break-all">{record.job_manifest_checksum}</code></details>}</td><td className="p-2">{LABEL[record.status] ?? record.status}</td>
              <td className="p-2">{stageMeta(record.current_stage)?.title ?? record.current_stage}</td><td className="p-2">{new Date(record.recorded_at).toLocaleString("vi-VN")}</td>
            </tr>)}
          </tbody></table></div>}
    </div>
  </details>;
}
