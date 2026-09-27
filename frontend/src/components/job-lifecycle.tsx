"use client";

/**
 * Điều khiển vòng đờ job (PRODUCT-02).
 *
 * Chỉ hiện những nút mà bảng chuyển trạng thái cho phép — nhưng backend vẫn là
 * nơi quyết định, nên lỗi 422/409 từ đó được hiện nguyên văn. Giấu nút chỉ để
 * đỡ bấm nhầm, không phải để thay thế kiểm tra ở backend.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { retryJob, transitionJob } from "@/lib/api/endpoints";
import { Button } from "@/components/ui/button";
import { JOB_TRANSITIONS, type JobManifest, type JobStatus } from "@/lib/contracts/api";

export function JobLifecycleControls({ job }: { job: JobManifest }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targets = JOB_TRANSITIONS[job.status].filter((status) => status !== "QUEUED");
  const canRetry = JOB_TRANSITIONS[job.status].includes("QUEUED");

  async function run(action: () => Promise<JobManifest>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      router.refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? `${cause.status}: ${cause.detail}` : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3" data-testid="lifecycle">
      <h2 className="mb-2 text-sm font-semibold text-slate-200">Vòng đờ</h2>
      <div className="flex flex-wrap gap-2">
        {targets.map((target: JobStatus) => (
          <Button
            key={target}
            variant="secondary"
            size="sm"
            busy={busy}
            onClick={() => run(() => transitionJob(job.job_id, { target_status: target }))}
          >
            → {target}
          </Button>
        ))}
        {canRetry && (
          <Button
            variant="primary"
            size="sm"
            busy={busy}
            onClick={() => run(() => retryJob(job.job_id))}
          >
            Retry (attempt mới)
          </Button>
        )}
        {targets.length === 0 && !canRetry && (
          <span className="text-xs text-slate-500">
            Trạng thái kết thúc — không còn chuyển nào hợp lệ.
          </span>
        )}
      </div>
      <p className="mt-2 text-[10px] text-slate-500">
        Đây là affordance mock-worker: chưa có worker thật nên ngườ dùng đóng vai ngườ báo tiến độ.
        Ghi SUCCEEDED cần artifact đầu ra resolve được và khớp checksum, nên không thể đánh dấu
        thành công giả.
      </p>
      {error && (
        <p
          role="alert"
          data-testid="lifecycle-error"
          className="mt-2 rounded bg-rose-950/60 p-2 text-xs text-rose-300"
        >
          {error}
        </p>
      )}
    </section>
  );
}
