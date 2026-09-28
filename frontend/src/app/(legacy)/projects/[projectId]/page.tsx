import Link from "next/link";

import { CreateJobButton } from "@/components/create-job";
import { PageHeader } from "@/components/shell";
import { Checksum, EmptyState, ErrorState, JobStatusBadge, PrivacyBadge } from "@/components/states";
import { getProject, listJobs } from "@/lib/api/endpoints";

export default async function ProjectDetailPage({ params }: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  const [project, jobs] = await Promise.all([getProject(projectId), listJobs(projectId)]);

  if (!project.ok) {
    return (
      <>
        <PageHeader title="Project" subtitle={projectId} />
        <ErrorState title="Không tải được project" detail={project.error.detail} />
      </>
    );
  }

  return (
    <>
      <PageHeader title={project.data.name} subtitle={project.data.project_id} />

      <section className="mb-6 grid gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4 text-sm md:grid-cols-2">
        <div>
          <h2 className="mb-2 text-xs tracking-wide text-slate-400 uppercase">Privacy</h2>
          <PrivacyBadge
            result={project.data.privacy.result}
            dispatchAllowed={project.data.privacy.dispatch_allowed}
          />
          {project.data.privacy.block_reason && (
            <p className="mt-2 text-xs text-amber-300">{project.data.privacy.block_reason}</p>
          )}
          <p className="mt-2 text-xs text-slate-400">
            Inspection scope: <span className="font-mono">{project.data.privacy.inspection_scope}</span> ·{" "}
            {project.data.privacy.unresolved_finding_count} finding chưa xử lý
          </p>
        </div>
        <div>
          <h2 className="mb-2 text-xs tracking-wide text-slate-400 uppercase">Source rights</h2>
          <pre className="overflow-x-auto rounded bg-slate-950 p-2 text-xs text-slate-300">
            {JSON.stringify(project.data.source_rights_attestation, null, 2)}
          </pre>
          <p className="mt-2 text-xs text-slate-500">
            <Checksum value={project.data.input_manifest_checksum} label="input manifest" />
          </p>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Jobs</h2>
          <CreateJobButton projectId={project.data.project_id} />
        </div>
        {!jobs.ok ? (
          <ErrorState title="Không tải được danh sách job" detail={jobs.error.detail} />
        ) : jobs.data.jobs.length === 0 ? (
          <EmptyState message="Project này chưa có job nào. Bấm “Tạo job mới” để bắt đầu." />
        ) : (
          <ul className="flex flex-col gap-2">
            {jobs.data.jobs.map((job) => (
              <li key={job.job_id}>
                <Link
                  href={`/jobs/${job.job_id}`}
                  className="flex flex-wrap items-center gap-3 rounded border border-slate-800 bg-slate-900/40 px-3 py-2 text-sm hover:border-slate-700"
                >
                  <span className="font-mono text-xs text-slate-300">{job.job_id}</span>
                  <JobStatusBadge status={job.status} />
                  <span className="text-xs text-slate-500">stage {job.current_stage}</span>
                  <span className="ml-auto text-xs text-slate-500">scene {job.scene_revision}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
