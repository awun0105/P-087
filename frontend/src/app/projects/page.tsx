import Link from "next/link";

import { PageHeader } from "@/components/shell";
import { Checksum, EmptyState, ErrorState, PrivacyBadge } from "@/components/states";
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
        subtitle="Privacy state hiển thị ngay ở đây vì nó quyết định project có được dispatch job hay không."
      />
      {result.data.projects.length === 0 ? (
        <EmptyState message="Chưa có project nào." />
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-slate-400">
              <th className="py-2">Project</th>
              <th className="py-2">Source</th>
              <th className="py-2">Privacy</th>
              <th className="py-2">Input checksum</th>
            </tr>
          </thead>
          <tbody>
            {result.data.projects.map((project) => (
              <tr key={project.project_id} className="border-b border-slate-900">
                <td className="py-2">
                  <Link
                    href={`/projects/${project.project_id}`}
                    className="text-sky-400 hover:text-sky-300"
                  >
                    {project.name}
                  </Link>
                  <div className="font-mono text-xs text-slate-500">{project.project_id}</div>
                </td>
                <td className="py-2 text-slate-300">{project.source_type}</td>
                <td className="py-2">
                  <PrivacyBadge
                    result={project.privacy.result}
                    dispatchAllowed={project.privacy.dispatch_allowed}
                  />
                </td>
                <td className="py-2">
                  <Checksum value={project.input_manifest_checksum} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
