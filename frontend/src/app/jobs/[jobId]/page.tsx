import Link from "next/link";

import { JobLifecycleControls } from "@/components/job-lifecycle";
import { JobTabs, PageHeader } from "@/components/shell";
import { Checksum, EmptyState, ErrorState, JobStatusBadge } from "@/components/states";
import { getJob, listJobArtifacts, listJobAttempts } from "@/lib/api/endpoints";

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
      <PageHeader title={job.data.job_id} subtitle={`project ${job.data.project_id}`} />
      <JobTabs jobId={jobId} active="Job" />

      <section className="mb-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm">
          <h2 className="mb-2 text-xs tracking-wide text-slate-400 uppercase">Trạng thái</h2>
          <JobStatusBadge status={job.data.status} />
          <p className="mt-2 text-xs text-slate-400">
            stage hiện tại: <span className="font-mono">{job.data.current_stage}</span>
          </p>
          <p className="text-xs text-slate-500">started {job.data.started_at}</p>
          <p className="text-xs text-slate-500">
            completed {job.data.completed_at ?? "—"}
          </p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm md:col-span-2">
          <h2 className="mb-2 text-xs tracking-wide text-slate-400 uppercase">Provenance</h2>
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
              <Checksum value={job.data.job_manifest_checksum} label="job manifest (canonical)" />
            </li>
          </ul>
          <p className="mt-2 text-xs text-slate-500">
            scene revision:{" "}
            <Link href={`/jobs/${jobId}/viewer`} className="text-sky-400 hover:text-sky-300">
              {job.data.scene_revision}
            </Link>
          </p>
        </div>
      </section>

      <div className="mb-4">
        <JobLifecycleControls job={job.data} />
      </div>

      <section className="mb-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Attempt</h2>
        {!attempts.ok ? (
          <ErrorState title="Không tải được attempt" detail={attempts.error.detail} />
        ) : attempts.data.attempts.length === 0 ? (
          <EmptyState message="Job chưa có attempt nào." />
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-400">
                <th className="py-2">#</th>
                <th className="py-2">Trạng thái</th>
                <th className="py-2">Stage</th>
                <th className="py-2">Ghi lúc</th>
                <th className="py-2">Revision manifest</th>
                <th className="py-2">Lỗi</th>
              </tr>
            </thead>
            <tbody>
              {attempts.data.attempts.map((attempt, index) => (
                <tr key={`${attempt.attempt}-${index}`} className="border-b border-slate-900">
                  <td className="py-2 font-mono">{attempt.attempt}</td>
                  <td className="py-2">
                    <JobStatusBadge status={attempt.status} />
                  </td>
                  <td className="py-2 font-mono text-xs text-slate-400">{attempt.current_stage}</td>
                  <td className="py-2 text-xs text-slate-400">{attempt.recorded_at}</td>
                  <td className="py-2">
                    <Checksum value={attempt.job_manifest_checksum} />
                  </td>
                  <td className="py-2 text-xs text-rose-300">
                    {attempt.error ? `${attempt.error.error_code}: ${attempt.error.human_message}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Artifact</h2>
        {!artifacts.ok ? (
          <ErrorState title="Không tải được artifact" detail={artifacts.error.detail} />
        ) : artifacts.data.artifacts.length === 0 ? (
          <EmptyState message="Chưa có artifact nào được publish cho job này." />
        ) : (
          <>
            <ul className="flex flex-col gap-1 text-sm">
              {artifacts.data.artifacts.map((artifact) => (
                <li key={artifact.artifact_uri} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-300">{artifact.artifact_uri}</span>
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
                    {artifact.data_class}
                  </span>
                  <Checksum value={artifact.artifact_checksum} />
                </li>
              ))}
            </ul>
            {artifacts.data.excluded_artifact_count > 0 && (
              <p className="mt-2 text-xs text-amber-300">
                {artifacts.data.excluded_artifact_count} artifact bị loại khỏi ranh giới product
                (ground_truth / evaluation_only).
              </p>
            )}
          </>
        )}
      </section>
    </>
  );
}
