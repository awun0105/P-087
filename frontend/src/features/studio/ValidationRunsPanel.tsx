"use client";

import { errorMessage } from "@/lib/ui-error";

import { useEffect, useRef, useState } from "react";

import { Badge, Button, Notice } from "@/components/studio/primitives";
import {
  cancelValidationRun,
  listValidationRuns,
  retryValidationRun,
  selectValidationRun,
  submitValidationRun,
  validationArtifactUrl,
} from "@/lib/api/studio";
import type { ValidationOperationStatus, ValidationRunView } from "@/lib/contracts/api";

const ACTIVE = new Set<ValidationOperationStatus>([
  "QUEUED",
  "WAITING_RESOURCES",
  "CLAIMED",
  "RUNNING",
  "CANCEL_REQUESTED",
]);

const STATUS: Record<ValidationOperationStatus, { label: string; tone: "neutral" | "ochre" | "sage" | "rust" | "ember" }> = {
  QUEUED: { label: "Đang chờ worker", tone: "ochre" },
  WAITING_RESOURCES: { label: "Chờ tài nguyên", tone: "ochre" },
  CLAIMED: { label: "Worker đã nhận", tone: "ember" },
  RUNNING: { label: "Đang chạy", tone: "ember" },
  CANCEL_REQUESTED: { label: "Đang yêu cầu hủy", tone: "ochre" },
  COMPLETED: { label: "Hoàn tất", tone: "sage" },
  FAILED: { label: "Thất bại", tone: "rust" },
  CANCELLED: { label: "Đã hủy", tone: "neutral" },
};

const ARTIFACTS = [
  ["report.json", "Report JSON"],
  ["runtime_manifest.json", "Runtime manifest"],
  ["execution.log", "Execution log"],
  ["observations.json", "Observations JSON"],
] as const;

export function ValidationRunsPanel({
  jobId,
  sceneRevision,
  candidateChecksum,
  canMutateJob,
  onSelected,
}: {
  jobId: string;
  sceneRevision: string;
  candidateChecksum: string | null;
  canMutateJob: boolean;
  onSelected?: () => void;
}) {
  const [snapshot, setSnapshot] = useState<{
    queryKey: string;
    runs: ValidationRunView[];
    error: string | null;
  } | null>(null);
  const [busy, setBusy] = useState<{ scope: string; key: string; token: number } | null>(null);
  const [reload, setReload] = useState(0);
  const scope = `${jobId}\u0000${sceneRevision}\u0000${candidateChecksum ?? ""}`;
  const queryKey = `${scope}\u0000${reload}`;
  const scopeRef = useRef(scope);
  const actionTokenRef = useRef(0);
  const loading = snapshot?.queryKey !== queryKey;
  const visibleRuns = snapshot?.queryKey === queryKey ? snapshot.runs : [];
  const visibleError = snapshot?.queryKey === queryKey ? snapshot.error : null;
  const busyKey = busy?.scope === scope ? busy.key : null;

  useEffect(() => {
    scopeRef.current = scope;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const load = async () => {
      try {
        const value = await listValidationRuns(jobId, controller.signal);
        if (controller.signal.aborted) return;
        setSnapshot({ queryKey, runs: value, error: null });
        if (value.some((run) => ACTIVE.has(run.status))) {
          timer = setTimeout(() => void load(), 5000);
        }
      } catch (cause: unknown) {
        if (!controller.signal.aborted) {
          setSnapshot((previous) => ({
            queryKey,
            runs: previous?.queryKey === queryKey ? previous.runs : [],
            error: errorMessage(cause, "Không đọc được lịch sử Isaac validation"),
          }));
        }
      }
    };

    void load();
    return () => {
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [jobId, sceneRevision, candidateChecksum, queryKey, scope]);

  async function mutate(key: string, action: () => Promise<ValidationRunView>, selected = false) {
    const actionScope = scope;
    const actionToken = ++actionTokenRef.current;
    setBusy({ scope: actionScope, key, token: actionToken });
    try {
      await action();
      if (scopeRef.current !== actionScope) return;
      setReload((value) => value + 1);
      if (selected) onSelected?.();
    } catch (cause: unknown) {
      if (scopeRef.current === actionScope) {
        setSnapshot((previous) => ({
          queryKey: `${actionScope}\u0000${reload}`,
          runs: previous?.queryKey === `${actionScope}\u0000${reload}` ? previous.runs : [],
          error: errorMessage(cause, "Không thực hiện được thao tác validation"),
        }));
      }
    } finally {
      setBusy((current) => (current?.token === actionToken ? null : current));
    }
  }

  const currentRuns = candidateChecksum ? visibleRuns.filter((run) => run.candidate_checksum === candidateChecksum) : [];
  const selectedRun = currentRuns.find((run) => run.selected) ?? null;
  const activeCurrentRun = currentRuns.some((run) => ACTIVE.has(run.status));

  return (
    <section className="space-y-3 p-5 text-sm" aria-label="Lịch sử Isaac validation">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-bold text-ink">Chạy kiểm tra bằng Isaac Sim</h3>
          <p className="mt-1 text-ink-muted">Mỗi lần chạy gắn với candidate và policy bất biến; kết quả chỉ được dùng sau khi chọn đúng run.</p>
        </div>
        {canMutateJob && candidateChecksum && (
          <Button
            size="sm"
            disabled={busyKey !== null || activeCurrentRun}
            onClick={() => void mutate("submit", () => submitValidationRun(jobId, candidateChecksum))}
          >
            {busyKey === "submit" && <span aria-hidden className="size-3 animate-spin rounded-full border-2 border-current border-r-transparent motion-reduce:animate-none" />}
            Chạy validation
          </Button>
        )}
      </div>

      {!candidateChecksum && <Notice tone="ochre">Tạo gói mô phỏng hợp lệ cho revision hiện tại trước khi chạy validation.</Notice>}
      {visibleError && (
        <div role="alert">
          <Notice tone="rust">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>{visibleError}</span>
              <Button size="sm" variant="secondary" disabled={busyKey !== null} onClick={() => setReload((value) => value + 1)}>Tải lại</Button>
            </div>
          </Notice>
        </div>
      )}
      {loading && <p role="status" className="text-ink-muted">Đang tải lịch sử validation…</p>}
      {!loading && !visibleError && visibleRuns.length === 0 && <p className="text-ink-muted">Chưa có lần chạy validation nào.</p>}

      {visibleRuns.length > 0 && (
        <ol className="space-y-2" aria-label="Các lần chạy validation">
          {visibleRuns.map((run) => {
            const isCurrent = run.candidate_checksum === candidateChecksum;
            const status = STATUS[run.status];
            const completed = run.status === "COMPLETED" && run.run_status === "COMPLETED" && run.report_checksum !== null;
            const busyThisRun = busyKey === run.run_id;
            return (
              <li key={run.run_id} className="space-y-2 rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={status.tone}>{status.label}</Badge>
                    <span className="text-ink-muted">Lần {run.attempt}</span>
                    {run.selected && <Badge tone="sage">Đang được dùng</Badge>}
                    {!isCurrent && <Badge tone="neutral">Candidate cũ</Badge>}
                  </div>
                  <time className="text-xs text-ink-subtle" dateTime={run.requested_at}>
                    {new Date(run.requested_at).toLocaleString("vi-VN")}
                  </time>
                </div>
                <p className="break-all font-mono text-xs text-ink-muted">{run.run_id} · {run.candidate_checksum.slice(0, 19)}</p>
                {run.error_code && <p className="text-rust">Mã lỗi: <code>{run.error_code}</code></p>}
                {run.status === "WAITING_RESOURCES" && <p className="text-ink-muted">Worker chưa chạy; đang chờ profile tài nguyên phù hợp.</p>}
                {run.status === "CANCEL_REQUESTED" && <p role="status" className="text-ink-muted">Đang chờ worker dừng tiến trình và xác nhận hủy.</p>}

                {completed && (
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                    {ARTIFACTS.map(([name, label]) => (
                      <a key={name} className="font-medium text-ember underline decoration-ember/40 underline-offset-2 hover:text-ember-strong" href={validationArtifactUrl(jobId, run.run_id, name)}>
                        Tải {label}
                      </a>
                    ))}
                  </div>
                )}

                {canMutateJob && isCurrent && (
                  <div className="flex flex-wrap gap-2">
                    {ACTIVE.has(run.status) && run.status !== "CANCEL_REQUESTED" && (
                      <Button size="sm" variant="secondary" disabled={busyKey !== null} onClick={() => void mutate(run.run_id, () => cancelValidationRun(jobId, run.run_id))}>
                        {busyThisRun ? "Đang cập nhật…" : "Hủy run"}
                      </Button>
                    )}
                    {run.status === "FAILED" && run.retryable && (
                      <Button size="sm" variant="secondary" disabled={busyKey !== null || activeCurrentRun} onClick={() => void mutate(run.run_id, () => retryValidationRun(jobId, run.run_id))}>
                        {busyThisRun ? "Đang cập nhật…" : "Thử lại"}
                      </Button>
                    )}
                    {completed && !run.selected && (
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={busyKey !== null}
                        onClick={() => void mutate(
                          run.run_id,
                          () => selectValidationRun(jobId, run.run_id, run.candidate_checksum, selectedRun?.run_id ?? null),
                          true,
                        )}
                      >
                        {busyThisRun ? "Đang chọn…" : "Dùng report này cho review"}
                      </Button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
