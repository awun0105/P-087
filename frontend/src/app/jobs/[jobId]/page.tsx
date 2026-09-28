import Link from "next/link";

import { JobLifecycleControls } from "@/components/job-lifecycle";
import { JobTabs, PageHeader } from "@/components/shell";
import { Checksum, EmptyState, ErrorState, JobStatusBadge } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { CopyButton } from "@/components/ui/copy-button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { getJob, listJobArtifacts, listJobAttempts } from "@/lib/api/endpoints";
import type {
  ArtifactDataClass,
  ExecutionError,
  JobAttempt,
  StageArtifact,
} from "@/lib/contracts/api";
import { StageTimeline } from "@/features/jobs/StageTimeline";

export default async function JobDetailPage({ params }: PageProps<"/jobs/[jobId]">) {
  const { jobId } = await params;
  const [job, attempts, artifacts] = await Promise.all([
    getJob(jobId),
    listJobAttempts(jobId),
    listJobArtifacts(jobId),
  ]);

  if (!job.ok) {
    return (
      <>
        <PageHeader title="Job" subtitle={jobId} />
        <ErrorState title="Không tải được job" detail={job.error.detail} />
      </>
    );
  }

  return (
    <>
      <PageHeader title={job.data.job_id} subtitle={`project: ${job.data.project_id}`} />
      <JobTabs jobId={jobId} active="Job" />

      {/* Status bar */}
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <Panel>
          <div className="p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              Trạng thái
            </h2>
            <JobStatusBadge status={job.data.status} />
            <p className="mt-2 text-xs text-slate-400">
              stage: <span className="font-mono text-slate-300">{job.data.current_stage}</span>
            </p>
            <p className="mt-1 text-xs text-slate-600">{job.data.started_at}</p>
            <p className="text-xs text-slate-600">completed: {job.data.completed_at ?? "—"}</p>
          </div>
        </Panel>

        <Panel className="md:col-span-2">
          <div className="p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              Provenance
            </h2>
            <ul className="flex flex-col gap-1">
              <li>
                <Checksum value={job.data.input_manifest_checksum} label="input" />
              </li>
              <li>
                <Checksum value={job.data.config_checksum} label="config" />
              </li>
              <li>
                <Checksum value={job.data.runtime_manifest_checksum} label="runtime" />
              </li>
              <li>
                <Checksum value={job.data.job_manifest_checksum} label="job manifest" />
              </li>
            </ul>
            <p className="mt-2 text-xs text-slate-500">
              scene revision:{" "}
              <Link href={`/jobs/${jobId}/viewer`} className="text-sky-400 hover:text-sky-300">
                {job.data.scene_revision}
              </Link>
            </p>
          </div>
        </Panel>
      </div>

      {/* Lifecycle controls */}
      <div className="mb-4">
        <JobLifecycleControls job={job.data} />
      </div>

      {/* Stage timeline (PRODUCT-09) */}
      <div className="mb-4">
        <StageTimeline stages={job.data.stage_artifacts} currentStage={job.data.current_stage ?? undefined} />
      </div>

      {/* Attempts */}
      <section className="mb-4">
        <Panel>
          <PanelHeader
            title="Lịch sử attempt"
            subtitle={`${attempts.ok ? attempts.data.attempts.length : "?"} lần chạy`}
          />
          {!attempts.ok ? (
            <div className="p-4">
              <ErrorState title="Không tải được attempt" detail={attempts.error.detail} />
            </div>
          ) : attempts.data.attempts.length === 0 ? (
            <div className="p-4">
              <EmptyState message="Job chưa có attempt nào." />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-500">
                    <th className="px-3 py-2">#</th>
                    <th className="px-3 py-2">Trạng thái</th>
                    <th className="px-3 py-2">Stage</th>
                    <th className="px-3 py-2">Ghi lúc</th>
                    <th className="px-3 py-2">Manifest</th>
                    <th className="px-3 py-2">Lỗi</th>
                  </tr>
                </thead>
                <tbody>
                  {attempts.data.attempts.map((attempt, index) => (
                    <AttemptRow
                      key={`${attempt.attempt}-${index}`}
                      attempt={attempt}
                      error={attemptError(job.data.stage_artifacts)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </section>

      {/* Artifacts */}
      <section>
        <ArtifactSection artifactsResponse={artifacts} />
      </section>
    </>
  );
}

/**
 * `JobAttemptRecord` không có field `error`; chi tiết lỗi của attempt nằm ở
 * `ExecutionError` của stage artifact mà job đang dừng, nên truyền vào từ ngoài.
 */
function attemptError(stages: StageArtifact[]): ExecutionError | null {
  return stages.find((stage) => stage.error !== null)?.error ?? null;
}

function AttemptRow({ attempt, error }: { attempt: JobAttempt; error: ExecutionError | null }) {
  return (
    <tr className="border-b border-slate-900 transition-colors hover:bg-slate-900/40">
      <td className="px-3 py-2 font-mono text-xs text-slate-400">{attempt.attempt}</td>
      <td className="px-3 py-2">
        <JobStatusBadge status={attempt.status} />
      </td>
      <td className="px-3 py-2 font-mono text-xs text-slate-500">{attempt.current_stage}</td>
      <td className="px-3 py-2 text-xs text-slate-500">{attempt.recorded_at}</td>
      <td className="px-3 py-2">
        <Checksum value={attempt.job_manifest_checksum} />
      </td>
      <td className="px-3 py-2 text-xs">
        {error ? (
          <details className="group">
            <summary className="cursor-pointer list-none">
              <span className="text-rose-400 hover:text-rose-300">
                {error.error_code}
                {error.retryable && (
                  <Badge tone="warn" className="ml-1.5">
                    retryable
                  </Badge>
                )}
              </span>
            </summary>
            <p className="mt-1 max-w-xs text-[10px] text-slate-400">
              {error.human_message}
            </p>
          </details>
        ) : (
          <span className="text-slate-600">—</span>
        )}
      </td>
    </tr>
  );
}

function ArtifactSection({
  artifactsResponse,
}: {
  artifactsResponse: Awaited<ReturnType<typeof listJobArtifacts>>;
}) {
  if (!artifactsResponse.ok) {
    return (
      <Panel>
        <div className="p-4">
          <ErrorState title="Không tải được artifact" detail={artifactsResponse.error.detail} />
        </div>
      </Panel>
    );
  }

  const { artifacts, excluded_artifact_count } = artifactsResponse.data;

  return (
    <Panel>
      <PanelHeader
        title="Artifact"
        subtitle={`${artifacts.length} publish${excluded_artifact_count > 0 ? ` · ${excluded_artifact_count} loại` : ""}`}
      />
      {artifacts.length === 0 ? (
        <div className="p-4">
          <EmptyState message="Chưa có artifact nào được publish cho job này." />
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-500">
                  <th className="px-3 py-2">Class</th>
                  <th className="px-3 py-2">Loại</th>
                  <th className="px-3 py-2">URI</th>
                  <th className="px-3 py-2">Checksum</th>
                  <th className="px-3 py-2">Stage</th>
                </tr>
              </thead>
              <tbody>
                {artifacts.map((artifact) => (
                  <tr
                    key={artifact.artifact_uri}
                    className="border-b border-slate-900 transition-colors hover:bg-slate-900/40"
                  >
                    <td className="px-3 py-2">
                      <ArtifactClassBadge dataClass={artifact.data_class} />
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-300">{artifact.artifact_type}</td>
                    <td className="px-3 py-2">
                      <span
                        className="inline-flex max-w-xs items-center gap-1 truncate font-mono text-xs text-slate-400"
                        title={artifact.artifact_uri}
                      >
                        {artifact.artifact_uri}
                        <CopyButton value={artifact.artifact_uri} />
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <Checksum value={artifact.artifact_checksum} />
                    </td>
                    <td className="px-3 py-2 font-mono text-[10px] text-slate-500">
                      {artifact.producer_stage}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {excluded_artifact_count > 0 && (
            <div className="border-t border-slate-800 px-4 py-2">
              <p className="text-xs text-amber-300">
                <Badge tone="warn" className="mr-1.5">
                  {excluded_artifact_count}
                </Badge>
                artifact bị loại (ground_truth / evaluation_only).
              </p>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

function ArtifactClassBadge({ dataClass }: { dataClass: ArtifactDataClass | null }) {
  if (!dataClass) return <span className="text-slate-500">—</span>;
  return <Badge tone={dataClass === "product_input" ? "info" : "default"}>{dataClass}</Badge>;
}
