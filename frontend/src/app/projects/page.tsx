import Link from "next/link";

import { PageHeader } from "@/components/shell";
import { Checksum, EmptyState, ErrorState, PrivacyBadge } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { listProjects } from "@/lib/api/endpoints";

export default async function ProjectsPage() {
  const result = await listProjects();

  if (!result.ok) {
    return (
      <>
        <PageHeader title="Projects" />
        <ErrorState title="Không tải được danh sách project" detail={result.error.detail} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="Privacy state quyết định project có được dispatch job hay không."
      />
      {result.data.projects.length === 0 ? (
        <EmptyState message="Chưa có project nào." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {result.data.projects.map((project) => (
            <Link
              key={project.project_id}
              href={`/projects/${project.project_id}`}
              className="group block"
            >
              <Panel className="h-full transition-all hover:border-sky-900/60 hover:bg-slate-800/40">
                <div className="p-4">
                  <div className="mb-3 flex items-start justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-200 group-hover:text-sky-300">
                        {project.name}
                      </h3>
                      <p className="mt-0.5 font-mono text-[10px] text-slate-500">
                        {project.project_id}
                      </p>
                    </div>
                    <PrivacyBadge
                      result={project.privacy.result}
                      dispatchAllowed={project.privacy.dispatch_allowed}
                    />
                  </div>

                  <div className="mb-3 grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded bg-slate-950/50 p-2">
                      <p className="text-[10px] text-slate-500">source</p>
                      <p className="font-medium text-slate-300">{project.source_type}</p>
                    </div>
                    <div className="rounded bg-slate-950/50 p-2">
                      <p className="text-[10px] text-slate-500">findings</p>
                      <p className="font-medium text-slate-300">
                        {project.privacy.unresolved_finding_count}
                      </p>
                    </div>
                  </div>

                  <div className="border-t border-slate-800 pt-2">
                    <Checksum value={project.input_manifest_checksum} label="input" />
                  </div>

                  {project.privacy.block_reason && (
                    <p className="mt-2 text-[10px] text-rose-400">
                      block: {project.privacy.block_reason}
                    </p>
                  )}
                </div>
              </Panel>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
