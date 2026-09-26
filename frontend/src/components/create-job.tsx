"use client";

/**
 * Nút tạo job, có hiện lỗi privacy gate tại chỗ.
 *
 * Không tự đoán trước là gate sẽ chặn: nó gọi API rồi hiện đúng `detail` backend
 * trả về. Đoán ở client sẽ che mất luật thật của backend.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { createJob } from "@/lib/api/endpoints";
import { Button } from "@/components/ui/button";

export function CreateJobButton({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ status: number; detail: string } | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const job = await createJob(projectId, {});
      router.push(`/jobs/${job.job_id}`);
      router.refresh();
    } catch (cause) {
      if (cause instanceof ApiError) {
        setError({ status: cause.status, detail: cause.detail });
      } else {
        setError({ status: 0, detail: String(cause) });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <Button onClick={submit} busy={busy} size="sm">
        Tạo job mới
      </Button>
      {error && (
        <p
          role="alert"
          data-testid="create-job-error"
          className={`mt-2 rounded p-2 text-xs ${
            error.status === 409 ? "bg-amber-950/60 text-amber-200" : "bg-rose-950/60 text-rose-200"
          }`}
        >
          {error.status === 409 ? "Bị privacy gate chặn — " : ""}
          {error.status}: {error.detail}
        </p>
      )}
    </div>
  );
}
